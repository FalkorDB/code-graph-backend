import tqdm
from pathlib import Path
from typing import Optional, Self
import tree_sitter_java
from tree_sitter import Language, Parser, Node, Point, Tree
from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from falkordb import FalkorDB

config = MultilspyConfig.from_dict({"code_language": "java"})
logger = MultilspyLogger()
lsp = SyncLanguageServer.create(config, logger, "/Users/aviavni/repos/JFalkorDB")

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)
files = {}

class Method:
    def __init__(self, node: Node):
        self.node = node
        self.calls: list[Node] = []
        self.resolved_calls: set[Method] = set()
        self.parent = None

    def add_call(self, method: Node):
        self.calls.append(method)

    def add_resolved_call(self, method: Self):
        self.resolved_calls.add(method)

class Type:
    def __init__(self):
        self.methods: dict[Node, Method] = {}

    def add_method(self, method: Method):
        method.parent = self
        self.methods[method.node] = method

class File:
    def __init__(self, path: Path, tree: Tree):
        self.path = path
        self.tree = tree
        self.types: dict[Node, Type] = {}

    def add_type(self, type: Type):
        self.parent = self
        self.types[type.node] = type

class Interface(Type):
    def __init__(self, node: Node):
        self.node = node
        self.extends: list[Interface] = []
        super().__init__()
    
    def add_extends_interface(self, interface: Node):
        self.extends.append(interface)

class Class(Type):
    def __init__(self, node: Node):
        self.node = node
        self.interfaces: list[Interface] = []
        self.resolved_interfaces: list[Interface] = []
        self.base_class: Optional[Node] = None
        self.resolved_base_class: Optional[Type] = None
        super().__init__()
    
    def add_implement_interface(self, interface: Node):
        self.interfaces.append(interface)

    def add_resolved_interface(self, interface: Interface):
        self.resolved_interfaces.append(interface)

    def set_base_class(self, base_class: Node):
        self.base_class = base_class

    def set_resolved_base_class(self, base_class: Self):
        self.resolved_base_class = base_class

class Enum(Type):
    def __init__(self, node: Node):
        self.node = node
        super().__init__()

def find_parent(node: Node, parent_types: list) -> Node:
    while node.type not in parent_types:
        node = node.parent
    return node

def find_calls(node:Node, method: Method):
    query = JAVA_LANGUAGE.query("(method_invocation) @reference.call")
    captures = query.captures(node)
    if 'reference.call' in captures:
        for caller in captures['reference.call']:
            method.add_call(caller)


def find_methods(node: Node, type: Type):
    query = JAVA_LANGUAGE.query("[(method_declaration) (constructor_declaration)] @definition.method")
    captures = query.captures(node)
    if 'definition.method' in captures:
        for method_dec in captures['definition.method']:
            type.add_method(Method(method_dec))
            find_calls(method_dec, type.methods[method_dec])


def find_type(node: Node, file: File):
    query = JAVA_LANGUAGE.query("[(class_declaration) (interface_declaration) (enum_declaration)] @type")
    captures = query.captures(node)
    if 'type' in captures:
        for type_dec in captures['type']:
            if type_dec.type == 'class_declaration':
                type = Class(type_dec)
                interfaces_query = JAVA_LANGUAGE.query("(super_interfaces (type_list (type_identifier) @interface))")
                interfaces_captures = interfaces_query.captures(type_dec)
                if 'interface' in interfaces_captures:
                    for interface in interfaces_captures['interface']:
                        type.add_implement_interface(interface)
                base_class_query = JAVA_LANGUAGE.query("(superclass (type_identifier) @base_class)")
                base_class_captures = base_class_query.captures(type_dec)
                if 'base_class' in base_class_captures:
                    base_class = base_class_captures['base_class'][0]
                    type.set_base_class(base_class)
            elif type_dec.type == 'interface_declaration':
                type = Interface(type_dec)
                query = JAVA_LANGUAGE.query("(extends_interfaces (type_list (type_identifier) @type))?")
                extends_captures = query.captures(type_dec)
                if 'type' in extends_captures:
                    for interface in extends_captures['type']:
                        type.add_extends_interface(interface)
            elif type_dec.type == 'enum_declaration':
                type = Enum(type_dec)
            file.add_type(type)
            find_methods(type_dec, type)

def resolve(lsp: SyncLanguageServer, path: Path, node: Node) -> list[tuple[File, Node]]:
    return [(files[Path(location['absolutePath'])], files[Path(location['absolutePath'])].tree.root_node.descendant_for_point_range(Point(location['range']['start']['line'], location['range']['start']['character']), Point(location['range']['end']['line'], location['range']['end']['character']))) for location in lsp.request_definition(str(path), node.start_point.row, node.start_point.column) if Path(location['absolutePath']) in files]

def resolve_type(lsp: SyncLanguageServer, path: Path, node: Node) -> list[Type]:
    res = []
    for file, resolved_node in resolve(lsp, path, node):
        type_dec = find_parent(resolved_node, ['class_declaration', 'interface_declaration', 'enum_declaration'])
        res.append(file.types[type_dec])
    return res

def resolve_method(lsp: SyncLanguageServer, path: Path, node: Node) -> list[Method]:
    res = []
    for file, resolved_node in resolve(lsp, path, node):
        method_dec = find_parent(resolved_node, ['method_declaration', 'constructor_declaration', 'class_declaration', 'interface_declaration', 'enum_declaration'])
        if method_dec.type in ['class_declaration', 'interface_declaration', 'enum_declaration']:
            continue
        type_dec = find_parent(method_dec, ['class_declaration', 'interface_declaration', 'enum_declaration'])
        res.append(file.types[type_dec].methods[method_dec])
    return res

for path in Path("/Users/aviavni/repos/JFalkorDB").rglob("*.java"):
    if 'test' in str(path):
        continue

    # Parse file
    source_code = path.read_bytes()
    tree = parser.parse(source_code)
    file = File(path, tree)
    files[path] = file

    find_type(tree.root_node, file)

with lsp.start_server():
    for path, file in tqdm.tqdm(files.items(), "Resolve file"):
        for type_dec, type in file.types.items():
            if isinstance(type, Class):
                type.resolved_interfaces.clear()
                for interface in type.interfaces:
                    for resolved_interface in resolve_type(lsp, path, interface):
                        type.add_resolved_interface(resolved_interface)
                if type.base_class:
                    resolved_class = resolve_type(lsp, path, type.base_class)
                    if len(resolved_class) == 1:
                        type.set_resolved_base_class(resolved_class[0])
            for method_dec, method in type.methods.items():
                method.resolved_calls.clear()
                for call in method.calls:
                    for resolved_method in resolve_method(lsp, path, call):
                        method.add_resolved_call(resolved_method)

graph = FalkorDB().select_graph("java")

try:
    graph.delete()
except:
    pass

graph.create_node_range_index("File", "path")
graph.create_node_range_index("Type", "name")
graph.create_node_range_index("Method", "name", "parameters")

nodes_created = 0
relationships_created = 0
for path, file in tqdm.tqdm(files.items(), "Save file hierarchy"):
    params = {"path": str(path)}
    query = "CREATE (file:File {path: $path})\n"
    for i, (class_dec, class_obj) in enumerate(file.types.items()):
        params[f"type_name_{i}"] = class_dec.child_by_field_name('name').text.decode('utf-8')
        query += f"CREATE (file)-[:DECLARE]->(type_{i}:Type {{name: $type_name_{i}}})\n"
        for j, (method_dec, method_obj) in enumerate(class_obj.methods.items()):
            params[f"method_name_{i}_{j}"] = method_dec.child_by_field_name('name').text.decode('utf-8')
            params[f"mathod_params_{i}_{j}"] = method_dec.child_by_field_name('parameters').text.decode('utf-8')
            query += f"CREATE (type_{i})-[:HAS_METHOD]->(method_{i}_{j}:Method {{name: $method_name_{i}_{j}, parameters: $mathod_params_{i}_{j}}})\n"
    res = graph.query(query, params)
    nodes_created += res.nodes_created
    relationships_created += res.relationships_created
print(f"Created {nodes_created} nodes and {relationships_created} relationships")

actual_calls = 0
expected_calls = 0
for path, file in tqdm.tqdm(files.items(), "Save calls"):
    for class_dec, class_obj in file.types.items():
        if isinstance(class_obj, Class):
            for interface in class_obj.resolved_interfaces:
                query = "MATCH (file:File {path: $path})\n"
                params = {"path": str(path)}
                query += f"MATCH (file)-[:DECLARE]->(type:Type {{name: $type_name}})\n"
                params["type_name"] = class_dec.child_by_field_name('name').text.decode('utf-8')
                query += f"MATCH (interface:Type {{name: $interface_name}})\n"
                params["interface_name"] = interface.node.child_by_field_name('name').text.decode('utf-8')
                query += f"MERGE (type)-[:IMPLEMENTS]->(interface)\n"
                query += "RETURN *"
                res = graph.query(query, params)
            if class_obj.resolved_base_class:
                query = "MATCH (file:File {path: $path})\n"
                params = {"path": str(path)}
                query += f"MATCH (file)-[:DECLARE]->(type:Type {{name: $type_name}})\n"
                params["type_name"] = class_dec.child_by_field_name('name').text.decode('utf-8')
                query += f"MATCH (base_class:Type {{name: $base_class_name}})\n"
                params["base_class_name"] = class_obj.resolved_base_class.node.child_by_field_name('name').text.decode('utf-8')
                query += f"MERGE (type)-[:EXTENDS]->(base_class)\n"
                query += "RETURN *"
                res = graph.query(query, params)
        for method_dec, method_obj in class_obj.methods.items():
            params = {}
            query = "MATCH (file:File {path: $path})\n"
            params["path"] = str(path)
            query += f"MATCH (file)-[:DECLARE]->(type:Type {{name: $type_name}})\n"
            params[f"type_name"] = class_dec.child_by_field_name('name').text.decode('utf-8')
            query += f"MATCH (type)-[:HAS_METHOD]->(caller:Method {{name: $method_name, parameters: $mathod_params}})\n"
            params[f"method_name"] = method_dec.child_by_field_name('name').text.decode('utf-8')
            params[f"mathod_params"] = method_dec.child_by_field_name('parameters').text.decode('utf-8')
            if len(method_obj.resolved_calls) == 0:
                continue
            for i, call in enumerate(method_obj.resolved_calls):
                params[f"callee_class_name_{i}"] = call.parent.node.child_by_field_name('name').text.decode('utf-8')
                params[f"callee_method_name_{i}"] = call.node.child_by_field_name('name').text.decode('utf-8')
                params[f"callee_mathod_params_{i}"] = call.node.child_by_field_name('parameters').text.decode('utf-8')
                query += f"MATCH (:Type {{name: $callee_class_name_{i}}})-[:HAS_METHOD]->(callee_{i}:Method {{name: $callee_method_name_{i}, parameters: $callee_mathod_params_{i}}})\n"
                query += f"MERGE (caller)-[:CALLS]->(callee_{i})\n"
                query += f"WITH file, type, caller\n"
            query += "RETURN *"
            res = graph.query(query, params)
            actual_calls += res.relationships_created
            expected_calls += len(method_obj.resolved_calls)
print(actual_calls, expected_calls, actual_calls == expected_calls)