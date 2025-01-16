"""Tools for running batch jobs on a k8s cluster."""

import dataclasses
import shlex
import functools
import subprocess
import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

from farconf import from_dict, to_dict
from farconf.cli import assign_from_dotlist
from names_generator import generate_name

from AmongUs.configs import RunConfig
from AmongUs.constants import PROJECT_SHORT, WANDB_ENTITY, WANDB_PROJECT
from AmongUs.utils.git import git_latest_commit, validate_git_repo

DEFAULT_JOB_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "k8s" / "batch_job.yaml"


@dataclasses.dataclass
class ClusterRunConfig:
    """Configuration for a single run on the cluster.

    Args:
        config: The run configuration.
        node_frac_needed: Fraction of a node needed for the run.
    """

    config: RunConfig
    node_frac_needed: float = 1.0


@dataclasses.dataclass(frozen=True)
class ClusterOptions:
    """Options for running jobs on the cluster.

    These are typically shared between multiple runs.
    """

    CONTAINER_TAG: str = "latest"
    COMMIT_HASH: str = dataclasses.field(default_factory=git_latest_commit)
    CPU: int = 4
    MEMORY: str = "20G"
    GPU: int = 1
    PRIORITY: str = "normal-batch"
    WANDB_ENTITY: str = WANDB_ENTITY
    WANDB_PROJECT: str = WANDB_PROJECT
    WANDB_MODE: str = "online"


def create_cluster_run_configs(
    base_experiment_config: RunConfig,
    override_args_and_node_frac_needed: Sequence[Tuple[Dict[str, Any], float]],
) -> list[ClusterRunConfig]:
    """Creates a list of configs from a base config and sequence of modification specs.

    Args:
        base_experiment_config: base config which will be used by all runs with some
            specified modifications.
        override_args_and_node_frac_needed: a sequence of tuples (override_args,
            node_frac_needed), where override_args are merged with the base config to
            produce a run config, and node_frac_needed is the fraction of a node
            needed for a run. override_args is a dictionary with dot-separated keys
            that correspond to the config structure.

    Returns:
        list of `ClusterRunConfig`s describing configurations to be run on the cluster.
    """
    run_configs = []

    for override_args, node_frac_needed in override_args_and_node_frac_needed:
        config = to_dict(deepcopy(base_experiment_config))
        assert isinstance(config, dict)
        for key, value in override_args.items():
            assign_from_dotlist(config, key, value)
        config = from_dict(config, RunConfig)

        run_configs.append(
            ClusterRunConfig(config=config, node_frac_needed=node_frac_needed)
        )

    return run_configs


def run_multiple(
    run_configs: Sequence[ClusterRunConfig],
    cluster_options: ClusterOptions = ClusterOptions(),
    job_template_path: Path = DEFAULT_JOB_TEMPLATE_PATH,
    dry_run: bool = False,
    print: int | None = 0,
) -> None:
    """Runs batch jobs on the cluster with the runs specified in `run_configs`.

    Args:
        run_configs: sequence of `ClusterRunConfig`s with configurations to be run.
        cluster_options: options for running jobs on the cluster.
        job_template_path: path to the job template to use. Can be overwritten by the --job-template
            command-line argument.
        dry_run: if True, only print the job configs without running them. Otherwise,
            submit the jobs to the cluster.
        print: number of runs to print. None = print all of them (due to how slices work).
    """

    validate_git_repo()

    if not all(
        [
            run_config.config.experiment_name == run_configs[0].config.experiment_name
            for run_config in run_configs
        ]
    ):
        raise ValueError("All configs should have the same experiment name.")

    jobs, launch_id = _create_jobs(run_configs, cluster_options, job_template_path)
    if print is None or print!=0:
        print("\n\n---\n\n".join(jobs[:print]))
        return

    yamls_for_all_jobs = "\n\n---\n\n".join(jobs)
    if not dry_run:
        print(f"Launching jobs with {launch_id=}...")
        subprocess.run(
            ["kubectl", "create", "-f", "-"],
            check=True,
            input=yamls_for_all_jobs.encode(),
        )
        print(
            "Jobs launched. To delete them run:\n"
            f"kubectl delete jobs -l launch-id={launch_id}"
        )


def _create_jobs(
    run_configs: Sequence[ClusterRunConfig], cluster_options: ClusterOptions, job_template_path: Path
) -> tuple[Sequence[str], str]:
    """Creates k8s job configs for the runs, together with a launch id."""
    launch_id = generate_name(style="hyphen")

    runs_by_containers = _organize_by_containers(run_configs)

    jobs = []
    index = 0
    for runs in runs_by_containers:
        jobs.append(
            _create_job_for_multiple_runs(runs, cluster_options, job_template_path, launch_id, index)
        )
        index += len(runs)

    return jobs, launch_id


@functools.lru_cache()
def get_template_str(template_path: Path) -> str:
    with template_path.open("r") as f:
        return f.read()


def _create_job_for_multiple_runs(
    runs: Sequence[RunConfig],
    cluster_options: ClusterOptions,
    job_template_path: Path,
    launch_id: str,
    start_index: int,
) -> str:
    """Creates a single k8s job config for runs to be run in a single container."""
    name = runs[0].experiment_name

    # K8s job/pod names should be short for readability (hence cutting the name).
    end_index = start_index + len(runs) - 1
    k8s_job_name = (
        f"{PROJECT_SHORT}-{name[:16]}-{start_index:03}"
        if len(runs) == 1
        else f"{PROJECT_SHORT}-{name[:16]}-{start_index:03}-{end_index:03}"
    ).replace("_", "-")

    single_commands = []
    for i, run in enumerate(runs):
        run.run_name = f"{name}-{start_index+i:03}"
        split_command = ["python", run.script_path, *run.to_cli()]
        single_commands.append(shlex.join(split_command))
    single_commands.append("wait")
    command = "(" + " & ".join(single_commands) + ")"

    cluster_options_dict = to_dict(cluster_options)
    assert isinstance(cluster_options_dict, dict)

    job = get_template_str(job_template_path).format(
        NAME=k8s_job_name,
        COMMAND=command,
        LAUNCH_ID=launch_id,
        **cluster_options_dict,
    )

    return job


def _organize_by_containers(
    cluster_runs: Sequence[ClusterRunConfig],
) -> list[list[RunConfig]]:
    """Splits runs into groups that will be run together in a single k8s container."""
    # Sort from "less demanding" to "more demanding" jobs.
    cluster_runs = sorted(cluster_runs, key=lambda run: run.node_frac_needed)

    current_container: list[RunConfig] = []
    current_weight = 0.0
    runs_by_containers = [current_container]

    for cluster_run in cluster_runs:
        # Run can fit into the current container.
        if current_weight + cluster_run.node_frac_needed <= 1:
            current_container.append(cluster_run.config)
            current_weight += cluster_run.node_frac_needed
        else:
            current_container = [cluster_run.config]
            current_weight = cluster_run.node_frac_needed
            runs_by_containers.append(current_container)

    return runs_by_containers


def run_multiple_cli(run_configs: Sequence[ClusterRunConfig], cluster_options: ClusterOptions, job_template_path: Path=DEFAULT_JOB_TEMPLATE_PATH) -> None:
    """Runs or prints batch jobs on the cluster with the runs specified in `run_configs`.

    Args:
        run_configs: sequence of `ClusterRunConfig`s with configurations to be run.
        cluster_options: extra options for the job template.
        job_template_path: path to the job template to use. Can be overwritten by the --job-template
            command-line argument.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry_run",
        "-d",
        "--dry-run",
        action="store_true",
        default=False,
        help="Do not submit jobs to the cluster.",
    )
    parser.add_argument(
        "--print",
        "-p",
        "--print",
        type=str,
        default=0,
        help="Number of runs to print (default 0). Maybe an int or \"all\"",
    )
    parser.add_argument(
        "--job_template",
        "-t", "--job-template", type=Path, default=job_template_path,
        help="Path to the template YAML used to instantiate jobs.")
    args = parser.parse_args(argv)
    return run_multiple(
        run_configs,
        cluster_options,
        job_template_path=args.job_template,
        dry_run=args.dry_run,
        print=args.print,
    )
