import os
import subprocess
from multilspy import SyncLanguageServer
from pathlib import Path

import toml
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
    
    def add_dependencies(self, path: Path, files: list[Path]):
        if Path(f"{path}/venv").is_dir():
            return
        subprocess.run(["python3", "-m", "venv", "venv"], cwd=str(path))
        if Path(f"{path}/pyproject.toml").is_file():
            subprocess.run(["pip", "install", "poetry"], cwd=str(path), env={"VIRTUAL_ENV": f"{path}/venv", "PATH": f"{path}/venv/bin:{os.environ['PATH']}"})
            subprocess.run(["poetry", "install"], cwd=str(path), env={"VIRTUAL_ENV": f"{path}/venv", "PATH": f"{path}/venv/bin:{os.environ['PATH']}"})
            with open(f"{path}/pyproject.toml", 'r') as file:
                pyproject_data = toml.load(file)
                for requirement in pyproject_data.get("tool").get("poetry").get("dependencies"):
                    files.extend(Path(f"{path}/venv/lib").rglob(f"**/site-packages/{requirement}/*.py"))
        elif Path(f"{path}/requirements.txt").is_file():
            subprocess.run(["pip", "install", "-r", "requirements.txt"], cwd=str(path), env={"VIRTUAL_ENV": f"{path}/venv", "PATH": f"{path}/venv/bin:{os.environ['PATH']}"})
            with open(f"{path}/requirements.txt", 'r') as file:
                requirements = [line.strip().split("==") for line in file if line.strip()]
                for requirement in requirements:
                    files.extend(Path(f"{path}/venv/lib/").rglob(f"**/site-packages/{requirement}/*.py"))

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

    def is_dependency(self, file_path: str) -> bool:
        return "venv" in file_path

    def resolve_path(self, file_path: str, path: Path) -> str:
        return file_path

    def resolve_type(self, files: dict[Path, File], lsp: SyncLanguageServer, file_path: Path, path, node: Node) -> list[Entity]:
        res = []
        if node.type == 'attribute':
            node = node.child_by_field_name('attribute')
        for file, resolved_node in self.resolve(files, lsp, file_path, path, node):
            type_dec = self.find_parent(resolved_node, ['class_definition'])
            if type_dec in file.entities:
                res.append(file.entities[type_dec])
        return res

    def resolve_method(self, files: dict[Path, File], lsp: SyncLanguageServer, file_path: Path, path: Path, node: Node) -> list[Entity]:
        res = []
        if node.type == 'call':
            node = node.child_by_field_name('function')
            if node.type == 'attribute':
                node = node.child_by_field_name('attribute')
        for file, resolved_node in self.resolve(files, lsp, file_path, path, node):
            method_dec = self.find_parent(resolved_node, ['function_definition', 'class_definition'])
            if not method_dec:
                continue
            if method_dec in file.entities:
                res.append(file.entities[method_dec])
        return res
    
    def resolve_symbol(self, files: dict[Path, File], lsp: SyncLanguageServer, file_path: Path, path: Path, key: str, symbol: Node) -> Entity:
        if key in ["base_class", "parameters", "return_type"]:
            return self.resolve_type(files, lsp, file_path, path, symbol)
        elif key in ["call"]:
            return self.resolve_method(files, lsp, file_path, path, symbol)
        else:
            raise ValueError(f"Unknown key {key}")

    def add_file_imports(self, file: File) -> None:
        """
        Extract and add import statements from the file.
        """
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Query for both import types
            import_query = self.language.query("""
                (import_statement) @import
                (import_from_statement) @import_from
            """)
        
        captures = import_query.captures(file.tree.root_node)
        
        # Add all import statement nodes to the file
        if 'import' in captures:
            for import_node in captures['import']:
                file.add_import(import_node)
        
        if 'import_from' in captures:
            for import_node in captures['import_from']:
                file.add_import(import_node)

    def resolve_import(self, files: dict[Path, File], lsp: SyncLanguageServer, file_path: Path, path: Path, import_node: Node) -> list[Entity]:
        """
        Resolve an import statement to the entities it imports.
        """
        res = []
        
        # For import statements like "import os" or "from pathlib import Path"
        # We need to find the dotted_name nodes that represent the imported modules/names
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if import_node.type == 'import_statement':
                # Handle "import module" or "import module as alias"
                # Look for dotted_name or aliased_import
                query = self.language.query("(dotted_name) @module (aliased_import) @aliased")
            else:  # import_from_statement
                # Handle "from module import name"
                # Get the imported names (after the 'import' keyword)
                query = self.language.query("""
                    (import_from_statement
                        (dotted_name) @imported_name)
                """)
        
        captures = query.captures(import_node)
        
        # Try to resolve each imported name
        if 'module' in captures:
            for module_node in captures['module']:
                resolved = self.resolve_type(files, lsp, file_path, path, module_node)
                res.extend(resolved)
        
        if 'aliased' in captures:
            for aliased_node in captures['aliased']:
                # Get the actual module name from the aliased import
                if aliased_node.child_count > 0:
                    module_name_node = aliased_node.children[0]
                    resolved = self.resolve_type(files, lsp, file_path, path, module_name_node)
                    res.extend(resolved)
        
        if 'imported_name' in captures:
            for name_node in captures['imported_name']:
                resolved = self.resolve_type(files, lsp, file_path, path, name_node)
                res.extend(resolved)
        
        return res
