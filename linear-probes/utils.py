import gc
import torch as t

def free_unused_memory():
    """
    Frees unused memory on both RAM and GPU.
    """

    # Free unused memory in RAM
    gc.collect()

    # Free unused memory in GPU
    if t.cuda.is_available():
        t.cuda.empty_cache()
        t.cuda.ipc_collect()
