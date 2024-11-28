import io
from pathlib import Path
from abc import ABC, abstractmethod

class AbstractAnalyzer(ABC):
    @abstractmethod
    def first_pass(self, path: Path, f: io.TextIOWrapper) -> None:
        """
        Perform the first pass of analysis on the given file.

        Args:
            path (Path): The path to the file being processed.
            f (io.TextIOWrapper): The file object.
        """

        pass

    @abstractmethod
    def second_pass(self, path: Path, f: io.TextIOWrapper) -> None:
        """
        Perform a second pass analysis on the given source file.

        Args:
            path (Path): The path to the file.
            f (io.TextIOWrapper): The file handle of the file to be processed.
        """

        pass