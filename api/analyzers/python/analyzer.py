from multilspy import SyncLanguageServer
from pathlib import Path
from ...entities import *
from typing import Optional
from ..analyzer import AbstractAnalyzer

import tree_sitter_python as tspython
from tree_sitter import Language, Node

import logging
logger = logging.getLogger('code_graph')

class PythonAnalyzer(AbstractAnalyzer):
    def __init__(self) -> None:
        super().__init__(Language(tspython.language()))

    def get_entity_label(self, node: Node) -> str:
        if node.type == 'class_definition':
            return "Class"
        elif node.type == 'function_definition':
            return "Function"
        raise ValueError(f"Unknown entity type: {node.type}")

    def get_entity_name(self, node: Node) -> str:
        if node.type in ['class_definition', 'function_definition']:
            return node.child_by_field_name('name').text.decode('utf-8')
        raise ValueError(f"Unknown entity type: {node.type}")
    
    def get_entity_docstring(self, node: Node) -> Optional[str]:
        if node.type in ['class_definition', 'function_definition']:
            body = node.child_by_field_name('body')
            if body.child_count > 0 and body.children[0].type == 'expression_statement':
                docstring_node = body.children[0].child(0)
                return docstring_node.text.decode('utf-8')
            return None
        raise ValueError(f"Unknown entity type: {node.type}")        
    
    def get_entity_types(self) -> list[str]:
        return ['class_definition', 'function_definition']
    
    def add_symbols(self, entity: Entity) -> None:
        if entity.node.type == 'class_definition':
            superclasses = entity.node.child_by_field_name("superclasses")
            if superclasses:
                base_classes_query = self.language.query("(argument_list (_) @base_class)")
                base_classes_captures = base_classes_query.captures(superclasses)
                if 'base_class' in base_classes_captures:
                    for base_class in base_classes_captures['base_class']:
                        entity.add_symbol("base_class", base_class)
        elif entity.node.type == 'function_definition':
            query = self.language.query("(call) @reference.call")
            captures = query.captures(entity.node)
            if 'reference.call' in captures:
                for caller in captures['reference.call']:
                    entity.add_symbol("call", caller)
            query = self.language.query("(typed_parameter type: (_) @parameter)")
            captures = query.captures(entity.node)
            if 'parameter' in captures:
                for parameter in captures['parameter']:
                    entity.add_symbol("parameters", parameter)
            return_type = entity.node.child_by_field_name('return_type')
            if return_type:
                entity.add_symbol("return_type", return_type)

    def resolve_type(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
        res = []
        for file, resolved_node in self.resolve(files, lsp, path, node):
            type_dec = self.find_parent(resolved_node, ['class_definition'])
            res.append(file.entities[type_dec])
        return res

    def resolve_method(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
        res = []
        for file, resolved_node in self.resolve(files, lsp, path, node):
            method_dec = self.find_parent(resolved_node, ['function_definition', 'class_definition'])
            if not method_dec:
                continue
            if method_dec in file.entities:
                res.append(file.entities[method_dec])
        return res
    
    def resolve_symbol(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, key: str, symbol: Node) -> Entity:
        if key in ["base_class", "parameters", "return_type"]:
            return self.resolve_type(files, lsp, path, symbol)
        elif key in ["call"]:
            return self.resolve_method(files, lsp, path, symbol)
        else:
            raise ValueError(f"Unknown key {key}")
