import tqdm
from pathlib import Path
from typing import Self
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
        self.calls = []
        self.resolved_calls = []
        self.parent = None

    def add_call(self, method: Node):
        self.calls.append(method)

    def add_resolved_call(self, method: Self):
        self.resolved_calls.append(method)

class Type:
    def __init__(self):
        self.methods = {}

    def add_method(self, method: Method):
        method.parent = self
        self.methods[method.node] = method

class File:
    def __init__(self, path: Path, tree: Tree):
        self.path = path
        self.tree = tree
        self.types = {}

    def add_type(self, type: Type):
        self.parent = self
        self.types[type.node] = type

class Interface(Type):
    def __init__(self, node: Node):
        self.node = node
        self.extends = []
        super().__init__()
    
    def add_extends_interface(self, interface: str):
        self.extends.append(interface)

class Class(Type):
    def __init__(self, node: Node):
        self.node = node
        self.interfaces = []
        self.resolved_interfaces = []
        super().__init__()
    
    def add_implement_interface(self, interface: str):
        self.interfaces.append(interface)

    def add_resolved_interface(self, interface: Interface):
        self.resolved_interfaces.append(interface)

    def add_base_class(self, base_class: str):
        self.base_class = base_class

class Enum(Type):
    def __init__(self, node: Node):
        self.node = node
        super().__init__()

def find_parent(node: Node, parent_types: list):
    while node.type not in parent_types:
        node = node.parent
    return node

def find_calls(node:Node, method: Method):
    query = JAVA_LANGUAGE.query("(method_invocation) @reference.call")
    captures = query.captures(tree.root_node)
    if 'reference.call' in captures:
        for caller in captures['reference.call']:
            method.add_call(caller)


def find_methods(node: Node, type: Type):
    query = JAVA_LANGUAGE.query("(method_declaration) @definition.method")
    captures = query.captures(node)
    if 'definition.method' in captures:
        for method_dec in captures['definition.method']:
            type.add_method(Method(method_dec))
            find_calls(method_dec, type.methods[method_dec])

    query = JAVA_LANGUAGE.query("(constructor_declaration) @definition.method")
    captures = query.captures(node)
    if 'definition.method' in captures:
        for constructor_dec in captures['definition.method']:
            type.add_method(Method(constructor_dec))
            find_calls(constructor_dec, type.methods[constructor_dec])


def find_classes(node: Node, file: File):
    query = JAVA_LANGUAGE.query("(class_declaration) @definition.class")
    captures = query.captures(node)
    if 'definition.class' in captures:
        for class_dec in captures['definition.class']:
            type = Class(class_dec)
            file.add_type(type)
            interfaces_query = JAVA_LANGUAGE.query("(super_interfaces (type_list (type_identifier) @interface))")
            interfaces_captures = interfaces_query.captures(class_dec)
            if 'interface' in interfaces_captures:
                for interface in interfaces_captures['interface']:
                    type.add_implement_interface(interface)
            base_class_query = JAVA_LANGUAGE.query("(superclass (type_identifier) @base_class)")
            base_class_captures = base_class_query.captures(class_dec)
            if 'base_class' in base_class_captures:
                base_class = base_class_captures['base_class'][0]
                type.add_base_class(base_class)
            find_methods(class_dec, type)

def find_interfaces(node: Node, file: File):
    query = JAVA_LANGUAGE.query("(interface_declaration) @definition.interface")
    captures = query.captures(node)
    if 'definition.interface' in captures:
        for i, interface_dec in enumerate(captures['definition.interface']):
            type = Interface(interface_dec)
            file.add_type(type)
            query = JAVA_LANGUAGE.query("(extends_interfaces (type_list (type_identifier) @type))?")
            extends_captures = query.captures(interface_dec)
            if 'type' in extends_captures:
                for interface in extends_captures['type']:
                    type.add_extends_interface(interface)
            find_methods(interface_dec, type)

def find_enums(node: Node, file: File):
    query = JAVA_LANGUAGE.query("(enum_declaration) @definition.enum")
    captures = query.captures(node)
    if 'definition.enum' in captures:
        for enum_dec in captures['definition.enum']:
            type = Enum(enum_dec)
            file.add_type(type)
            find_methods(enum_dec, type)

def resolve_call(lsp: SyncLanguageServer, path: Path, call: Node, method: Method):
    locations = lsp.request_definition(str(path), call.start_point.row, call.start_point.column)
    for location in locations:
        path = Path(location['absolutePath'])
        if path not in files:
            continue
        callee_method_dec = files[path].tree.root_node.descendant_for_point_range(Point(location['range']['start']['line'], location['range']['start']['character']), Point(location['range']['end']['line'], location['range']['end']['character']))
        callee_method_dec = find_parent(callee_method_dec, ['method_declaration', 'constructor_declaration', 'field_declaration', 'enum_declaration', 'interface_declaration', 'class_declaration'])
        if callee_method_dec.type in ['field_declaration', 'enum_declaration', 'interface_declaration', 'class_declaration']:
            continue
        callee_class_dec = find_parent(callee_method_dec, ['class_declaration', 'interface_declaration', 'enum_declaration'])
        method.add_resolved_call(files[path].types[callee_class_dec].methods[callee_method_dec])

def resolve_interfaces(lsp: SyncLanguageServer, path: Path, class_type: Class):
    for interface in class_type.interfaces:
        locations = lsp.request_definition(str(path), interface.start_point.row, interface.start_point.column)
        for location in locations:
            path = Path(location['absolutePath'])
            if path not in files:
                continue
            interface_dec = files[path].tree.root_node.descendant_for_point_range(Point(location['range']['start']['line'], location['range']['start']['character']), Point(location['range']['end']['line'], location['range']['end']['character']))
            interface_dec = find_parent(interface_dec, ['interface_declaration'])
            class_type.add_resolved_interface(files[path].types[interface_dec])

for path in Path("/Users/aviavni/repos/JFalkorDB").rglob("*.java"):
    if 'test' in str(path):
        continue

    # Parse file
    source_code = path.read_bytes()
    tree = parser.parse(source_code)
    file = File(path, tree)
    files[path] = file

    find_classes(tree.root_node, file)
    find_interfaces(tree.root_node, file)
    find_enums(tree.root_node, file)

with lsp.start_server():
    for path, file in tqdm.tqdm(files.items(), "Resolve file"):
        for type_dec, type in file.types.items():
            if isinstance(type, Class):
                type.resolved_interfaces.clear()
                resolve_interfaces(lsp, path, type)
            for method_dec, method in type.methods.items():
                method.resolved_calls.clear()
                for call in method.calls:
                    resolve_call(lsp, path, call, method)

graph = FalkorDB().select_graph("java")

try:
    graph.delete()
except:
    pass

graph.create_node_range_index("File", "path")
graph.create_node_range_index("Class", "name")
graph.create_node_range_index("Method", "name", "parameters")

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
    graph.query(query, params)

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
                print(res.relationships_created)
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
