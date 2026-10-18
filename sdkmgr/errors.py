class SDKError(Exception):
    """A tool could not be resolved, downloaded, or installed safely."""


class InstallationRequired(SDKError):
    """Installation was deferred; run command and retry the original operation."""

    def __init__(self, command: tuple[str, ...], message: str):
        self.command = command
        super().__init__(message)
