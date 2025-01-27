from pathlib import Path

from tree_sitter import Language, Node, Parser
from api.entities.entity import Entity
from api.entities.file import File
from api.graph import Graph
from abc import ABC, abstractmethod
from multilspy import SyncLanguageServer

class AbstractAnalyzer(ABC):
    def __init__(self, language: Language) -> None:
        self.language = language
        self.parser = Parser(language)
    
    @abstractmethod
    def get_top_level_entity_types(self) -> list[str]:
        """
        Get the top level entity types for the language.

        Returns:
            list[str]: The list of top level entity types.
        """

        pass

    @abstractmethod
    def add_symbols(self, entity: Entity) -> None:
        """
        Add symbols to the entity.

        Args:
            entity (Entity): The entity to add symbols to.
        """

        pass

    @abstractmethod
    def add_children(self, entity: Entity) -> None:
        """
        Add children to the entity.

        Args:
            entity (Entity): The entity to add children to.
        """

        pass

    @abstractmethod
    def resolve_symbol(self, lsp: SyncLanguageServer, path: Path, key: str, symbol: Node) -> Entity:
        """
        Resolve a symbol to an entity.

        Args:
            lsp (SyncLanguageServer): The language server.
            path (Path): The path to the file.
            key (str): The symbol key.
            symbol (Node): The symbol node.

        Returns:
            Entity: The entity.
        """

        pass

