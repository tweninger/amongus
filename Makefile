ANSI_COLOR_TITLE=\033[31;1m
# Red and bold. See https://stackoverflow.com/a/33206814/4521118
ANSI_COLOR_TARGET=\033[32;1m
# Green and bold
ANSI_COLOR_RESET=\033[0m
ifneq (${NO_COLOR}, )
ANSI_COLOR_TITLE=
ANSI_COLOR_TARGET=
ANSI_COLOR_RESET=
endif

#%% Normal commands

.PHONY: help
help:
#% Print help from special comments in Makefile
	@awk \
		'/^#% / {sub(/#% */,"\t"); print} \
		/^#%% / {sub(/#%% */,""); print "${ANSI_COLOR_TITLE}" $$0 "${ANSI_COLOR_RESET}"} \
		/^[^=:\t ]+:/ && !/\.PHONY:/ \
			{sub(/:.*/, ""); \
				print "\n  ${ANSI_COLOR_TARGET}" \
					$$0 \
					"${ANSI_COLOR_RESET}" \
			}' \
		Makefile
