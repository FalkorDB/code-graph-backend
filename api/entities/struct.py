from typing import Optional
from typing import List

class Struct():
    """
    Represents a struct with a name and an optional docstring.
    """

    def __init__(self, path: str, name: str, doc: Optional[str],
                 src_start: int, src_end: int) -> None:
        """
        Initializes a Struct instance.

        Args:
            path (str): The path under which the struct is defined
            name (str): The name of the struct.
            doc (Optional[str], optional): The docstring of the struct. Defaults to None.
            src_start (int): Start line of the struct in the source code.
            src_end (int): End line of the struct in the source code.
        """

        self.path      = path
        self.name      = name
        self.doc       = doc
        self.src_start = src_start
        self.src_end   = src_end

        self.fields: List[List[str, str]] = []

    def __str__(self) -> str:
        return f"""
            id:        {self.id if hasattr(self, 'id') else 'Unknown'}
            path:      {self.path}
            name:      {self.name}
            doc:       {self.doc}
            src_start: {self. src_start}
            src_end:   {self.src_end}
            fields:    {self.fields}"""

    def __eq__(self, other):
        if not isinstance(other, Struct):
            return False

        return (self.path      == other.path      and
                self.name      == other.name      and
                self.doc       == other.doc       and
                self.src_start == other.src_start and
                self.src_end   == other.src_end   and
                self.fields    == other.fields)

    def add_field(self, name: str, t: str) -> None:
        """
        Add a field to the struct.

        Args:
            name (str): Name of the argument.
            t (str): Type of the field.
        """

        self.fields.append([name, t])

