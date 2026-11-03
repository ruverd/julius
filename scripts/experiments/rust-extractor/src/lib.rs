// Experiment-only TypeScript structural extractor. Same MIT-derived semantics as
// src/graph/{extract,bindings}.ts; upstream provenance remains in PROVENANCE.md.
use serde_json::{json, Value};
use std::{cell::RefCell, collections::{HashMap, HashSet}, ffi::{c_char, c_void, CStr}, ptr};

#[repr(C)]
#[derive(Clone, Copy)]
struct Point { row: u32, column: u32 }
#[repr(C)]
#[derive(Clone, Copy)]
struct Node { context: [u32; 4], id: *const c_void, tree: *const c_void }
extern "C" {
    fn ts_parser_new() -> *mut c_void;
    fn ts_parser_delete(parser: *mut c_void);
    fn ts_parser_set_language(parser: *mut c_void, language: *const c_void) -> bool;
    fn ts_parser_parse_string(parser: *mut c_void, old: *const c_void, text: *const c_char, length: u32) -> *mut c_void;
    fn ts_tree_delete(tree: *mut c_void);
    fn ts_tree_root_node(tree: *const c_void) -> Node;
    fn ts_node_type(node: Node) -> *const c_char;
    fn ts_node_start_byte(node: Node) -> u32;
    fn ts_node_end_byte(node: Node) -> u32;
    fn ts_node_start_point(node: Node) -> Point;
    fn ts_node_end_point(node: Node) -> Point;
    fn ts_node_parent(node: Node) -> Node;
    fn ts_node_named_child_count(node: Node) -> u32;
    fn ts_node_named_child(node: Node, index: u32) -> Node;
    fn ts_node_child_count(node: Node) -> u32;
    fn ts_node_child(node: Node, index: u32) -> Node;
    fn ts_node_child_by_field_name(node: Node, name: *const c_char, length: u32) -> Node;
    fn tree_sitter_typescript() -> *const c_void;
    fn tree_sitter_tsx() -> *const c_void;
}
impl Node {
    fn exists(self) -> bool { !self.id.is_null() }
    fn kind(self) -> &'static str { if !self.exists() { "" } else { unsafe { CStr::from_ptr(ts_node_type(self)).to_str().unwrap() } } }
    fn field(self, name: &str) -> Node { unsafe { ts_node_child_by_field_name(self, name.as_ptr().cast(), name.len() as u32) } }
    fn parent(self) -> Node { unsafe { ts_node_parent(self) } }
    fn children(self) -> impl Iterator<Item = Node> { (0..unsafe { ts_node_named_child_count(self) }).map(move |i| unsafe { ts_node_named_child(self, i) }) }
    fn all_children(self) -> impl Iterator<Item = Node> { (0..unsafe { ts_node_child_count(self) }).map(move |i| unsafe { ts_node_child(self, i) }) }
    fn start(self) -> usize { unsafe { ts_node_start_byte(self) as usize } }
    fn end(self) -> usize { unsafe { ts_node_end_byte(self) as usize } }
    fn text(self, source: &str) -> &str { if self.exists() { &source[self.start()..self.end()] } else { "" } }
    fn same(self, other: Node) -> bool { self.exists() && other.exists() && self.id == other.id && self.tree == other.tree }
}
struct Parser(*mut c_void);
impl Drop for Parser { fn drop(&mut self) { unsafe { ts_parser_delete(self.0) } } }
struct Tree(*mut c_void);
impl Drop for Tree { fn drop(&mut self) { unsafe { ts_tree_delete(self.0) } } }
thread_local! { static PARSER: RefCell<Parser> = RefCell::new(Parser(unsafe { ts_parser_new() })); }

fn function_value(kind: &str) -> bool { matches!(kind, "arrow_function" | "function" | "function_expression" | "generator_function") }
fn boundary(kind: &str) -> bool { matches!(kind, "function_declaration" | "generator_function_declaration" | "method_definition" | "arrow_function" | "function_expression" | "function") }
fn mapped(kind: &str) -> Option<&'static str> {
    match kind {
        "class_declaration" | "abstract_class_declaration" => Some("class"),
        "function_declaration" | "generator_function_declaration" => Some("function"),
        "method_definition" => Some("method"), "interface_declaration" => Some("interface"),
        "type_alias_declaration" => Some("type"), "enum_declaration" => Some("enum"), _ => None,
    }
}
fn descriptor(node: Node, source: &str) -> Option<(String, &'static str, usize)> {
    if let Some(kind) = mapped(node.kind()) {
        let name = node.field("name");
        if name.exists() { let body = node.field("body"); return Some((name.text(source).into(), kind, if body.exists() { body.start() } else { node.end() })); }
    } else if node.kind() == "variable_declarator" && function_value(node.field("value").kind()) {
        let name = node.field("name"); let body = node.field("value").field("body");
        if name.exists() { return Some((name.text(source).into(), "function", if body.exists() { body.start() } else { node.end() })); }
    }
    None
}
type Imports = HashMap<String, (String, String)>;
fn specifier(node: Node, source: &str) -> Option<String> {
    let string = node.children().find(|n| n.kind() == "string")?;
    Some(string.children().find(|n| n.kind() == "string_fragment").map(|n| n.text(source).to_string())
        .unwrap_or_else(|| string.text(source).trim_matches(['\'', '"']).to_string()))
}
fn collect_import_bindings(node: Node, source: &str, spec: &str, imports: &mut Imports) {
    if node.kind() == "import_specifier" {
        let name = node.field("name"); let alias = node.field("alias");
        if name.exists() { imports.insert(if alias.exists() { alias } else { name }.text(source).into(), (name.text(source).into(), spec.into())); }
        return;
    }
    for child in node.children() { collect_import_bindings(child, source, spec, imports); }
}
fn imports(node: Node, source: &str, out: &mut Imports, aliases: &mut HashMap<String, String>) {
    if node.kind() == "import_specifier" {
        let name = node.field("name"); let alias = node.field("alias");
        if name.exists() && alias.exists() { aliases.insert(alias.text(source).into(), name.text(source).into()); }
    }
    if node.kind() == "import_statement" {
        if let Some(spec) = specifier(node, source) { collect_import_bindings(node, source, &spec, out); }
    }
    for child in node.children() { imports(child, source, out, aliases); }
}
fn shadowed(node: Node, definition: Node, source: &str, names: &mut HashSet<String>) {
    if !node.same(definition) && !node.same(definition.field("value")) && boundary(node.kind()) {
        let name = node.field("name");
        if name.kind() == "identifier" { names.insert(name.text(source).into()); }
        return;
    }
    let name = match node.kind() {
        "variable_declarator" => node.field("name"),
        "required_parameter" | "optional_parameter" => node.field("pattern"), _ => node,
    };
    if name.kind() == "identifier" && (matches!(node.kind(), "variable_declarator" | "required_parameter" | "optional_parameter") || node.parent().kind() == "formal_parameters") {
        names.insert(name.text(source).into());
    }
    for child in node.children() { shadowed(child, definition, source, names); }
}
fn annotation(node: Node, source: &str, aliases: &HashMap<String, String>) -> Option<String> {
    if node.kind() != "type_annotation" { return None; }
    let ty = node.children().next()?;
    if ty.kind() != "type_identifier" { return None; }
    Some(aliases.get(ty.text(source)).cloned().unwrap_or_else(|| ty.text(source).into()))
}
fn new_type(node: Node, source: &str, aliases: &HashMap<String, String>) -> Option<String> {
    if node.kind() != "new_expression" || node.field("constructor").kind() != "identifier" { return None; }
    let name = node.field("constructor").text(source);
    Some(aliases.get(name).cloned().unwrap_or_else(|| name.into()))
}
fn bindings(node: Node, source: &str, scope: &[String], class_scope: Option<&str>, aliases: &HashMap<String, String>, out: &mut HashMap<String, String>) {
    let path = scope.join(".");
    match node.kind() {
        "variable_declarator" if !function_value(node.field("value").kind()) && node.field("name").kind() == "identifier" => {
            if let Some(ty) = new_type(node.field("value"), source, aliases).or_else(|| annotation(node.field("type"), source, aliases)) {
                out.insert(format!("{path}|{}", node.field("name").text(source)), ty);
            }
        }
        "public_field_definition" if node.field("name").exists() => {
            if let Some(ty) = annotation(node.field("type"), source, aliases).or_else(|| new_type(node.field("value"), source, aliases)) {
                out.insert(format!("{}|this.{}", class_scope.unwrap_or(&path), node.field("name").text(source)), ty);
            }
        }
        "required_parameter" if node.field("pattern").kind() == "identifier" => {
            if let Some(ty) = annotation(node.field("type"), source, aliases) {
                out.insert(format!("{path}|{}", node.field("pattern").text(source)), ty.clone());
                if node.all_children().any(|n| matches!(n.kind(), "accessibility_modifier" | "readonly" | "override_modifier")) {
                    out.insert(format!("{}|this.{}", class_scope.unwrap_or(&path), node.field("pattern").text(source)), ty);
                }
            }
        } _ => {}
    }
    let mut child_scope = scope.to_vec();
    if let Some((name, _, _)) = descriptor(node, source) { child_scope.push(name); }
    let class_path = child_scope.join(".");
    let child_class = if matches!(node.kind(), "class_declaration" | "abstract_class_declaration") { Some(class_path.as_str()) } else { class_scope };
    for child in node.children() { bindings(child, source, &child_scope, child_class, aliases, out); }
}
fn lookup(bindings: &HashMap<String, String>, scope: &[String], name: &str) -> Option<String> {
    for i in (0..=scope.len()).rev() {
        if let Some(ty) = bindings.get(&format!("{}|{name}", scope[..i].join("."))) { return Some(ty.clone()); }
    }
    None
}
struct Extract<'a> { source: &'a str, nodes: Vec<Value>, edges: Vec<Value>, minted: HashSet<String>, bindings: HashMap<String, String> }
impl Extract<'_> {
    fn walk(&mut self, node: Node, scope: &[String], parent: i64, class: Option<&str>, imported: &Imports) {
        if let Some((name, kind, header)) = descriptor(node, self.source) {
            let mut child_scope = scope.to_vec(); child_scope.push(name.clone());
            let base = child_scope.join("."); let mut id = base.clone(); let mut count = 2;
            while !self.minted.insert(id.clone()) { id = format!("{base}~{count}"); count += 1; }
            let ordinal = self.nodes.len() as i64;
            let mut ancestor = node.parent(); let mut exported = false;
            while ancestor.exists() { if ancestor.kind() == "export_statement" { exported = true; break; } ancestor = ancestor.parent(); }
            let start_row = unsafe { ts_node_start_point(node).row + 1 };
            let end_row = unsafe { ts_node_end_point(node).row + 1 };
            self.nodes.push(json!([id, name, kind, node.start(), node.end(), header, start_row, end_row, exported, if kind == "method" { class } else { None }]));
            self.edges.push(json!([parent, "contains", ordinal, null, null, null]));
            if kind == "class" {
                if let Some(heritage) = node.children().find(|n| n.kind() == "class_heritage") {
                    for clause in heritage.children() {
                        let relation = match clause.kind() { "implements_clause" => "implements", "extends_clause" => "extends", _ => continue };
                        for ty in clause.children().filter(|n| matches!(n.kind(), "identifier" | "type_identifier")) {
                            self.edges.push(json!([ordinal, relation, ty.text(self.source), null, null, null]));
                        }
                    }
                }
            }
            let mut filtered;
            let child_imported = if matches!(kind, "function" | "method") && !imported.is_empty() {
                let mut names = HashSet::new(); shadowed(node, node, self.source, &mut names);
                filtered = imported.clone(); filtered.retain(|name, _| !names.contains(name)); &filtered
            } else { imported };
            for child in node.children() { self.walk(child, &child_scope, ordinal, if kind == "class" { Some(&name) } else { class }, child_imported); }
            return;
        }
        if node.kind() == "import_statement" {
            if let Some(spec) = specifier(node, self.source).filter(|s| !s.is_empty()) { self.edges.push(json!([-1, "imports", null, null, null, spec])); }
            return;
        }
        if node.kind() == "call_expression" {
            let function = node.field("function");
            let call = if function.kind() == "identifier" { Some((function.text(self.source).to_string(), false, None)) }
                else if function.kind() == "member_expression" {
                    let property = function.field("property");
                    let property = if property.exists() { Some(property) } else { function.children().last() };
                    property.map(|p| {
                        let object = function.field("object");
                        let receiver = match object.kind() {
                            "this" => Some("this".into()), "identifier" => Some(object.text(self.source).into()),
                            "member_expression" if object.field("object").kind() == "this" && object.field("property").exists() => Some(format!("this.{}", object.field("property").text(self.source))),
                            _ => None,
                        };
                        (p.text(self.source).to_string(), true, receiver)
                    })
                } else { None };
            if let Some((name, member, receiver)) = call {
                let recv_type = receiver.and_then(|r: String| if matches!(r.as_str(), "this" | "self" | "cls") { class.map(String::from) }
                    else if r == "super" { None } else { lookup(&self.bindings, scope, &r).or_else(|| r.strip_prefix("this.").and_then(|s| lookup(&self.bindings, scope, &format!("self.{s}")))) });
                self.edges.push(json!([parent, "calls", name, member, recv_type, null]));
            }
        } else if node.kind() == "identifier" {
            let p = node.parent();
            let direct_call = p.kind() == "call_expression" && (p.field("function").same(node) || p.field("name").same(node));
            if !direct_call && !p.field("name").same(node) {
                if let Some((name, spec)) = imported.get(node.text(self.source)) { self.edges.push(json!([parent, "references", name, null, null, spec])); }
            }
        }
        for child in node.children() { self.walk(child, scope, parent, class, imported); }
    }
}
fn extract(source: &str, language: &str) -> Result<String, String> {
    if !matches!(language, "typescript" | "tsx") { return Err("Pilot supports typescript and tsx only".into()); }
    if source.len() > u32::MAX as usize { return Err("Source exceeds Tree-sitter byte limit".into()); }
    PARSER.with(|cell| {
        let parser = cell.borrow_mut();
        if parser.0.is_null() { return Err("Tree-sitter allocation failed".into()); }
        let grammar = unsafe { if language == "tsx" { tree_sitter_tsx() } else { tree_sitter_typescript() } };
        if !unsafe { ts_parser_set_language(parser.0, grammar) } { return Err("Tree-sitter ABI mismatch".into()); }
        let tree = Tree(unsafe { ts_parser_parse_string(parser.0, ptr::null(), source.as_ptr().cast(), source.len() as u32) });
        if tree.0.is_null() { return Err("Tree-sitter parse failed".into()); }
        let root = unsafe { ts_tree_root_node(tree.0) };
        let mut imported = HashMap::new(); let mut aliases = HashMap::new();
        imports(root, source, &mut imported, &mut aliases);
        let mut out = Extract { source, nodes: vec![], edges: vec![], minted: HashSet::new(), bindings: HashMap::new() };
        bindings(root, source, &[], None, &aliases, &mut out.bindings);
        for child in root.children() { out.walk(child, &[], -1, None, &imported); }
        Ok(json!([unsafe { ts_node_end_point(root).row + 1 }, out.nodes, out.edges]).to_string())
    })
}

// Minimal Node-API bridge; every borrowed JS value remains local to this call.
// catch_unwind prevents Rust panics from crossing the C ABI boundary.
type Handle = *mut c_void;
extern "C" {
    fn napi_get_cb_info(env: Handle, info: Handle, argc: *mut usize, argv: *mut Handle, this: *mut Handle, data: *mut Handle) -> i32;
    fn napi_get_value_string_utf8(env: Handle, value: Handle, buf: *mut c_char, size: usize, copied: *mut usize) -> i32;
    fn napi_create_string_utf8(env: Handle, value: *const c_char, size: usize, result: *mut Handle) -> i32;
    fn napi_throw_error(env: Handle, code: *const c_char, message: *const c_char) -> i32;
    fn napi_create_function(env: Handle, name: *const c_char, len: usize, callback: unsafe extern "C" fn(Handle, Handle) -> Handle, data: Handle, result: *mut Handle) -> i32;
    fn napi_set_named_property(env: Handle, object: Handle, name: *const c_char, value: Handle) -> i32;
}
unsafe fn js_string(env: Handle, value: Handle) -> Result<String, String> {
    let mut size = 0;
    if napi_get_value_string_utf8(env, value, ptr::null_mut(), 0, &mut size) != 0 { return Err("Expected string argument".into()); }
    let mut buffer = vec![0u8; size + 1];
    if napi_get_value_string_utf8(env, value, buffer.as_mut_ptr().cast(), buffer.len(), &mut size) != 0 { return Err("Failed to read string".into()); }
    buffer.truncate(size); String::from_utf8(buffer).map_err(|e| e.to_string())
}
unsafe extern "C" fn callback(env: Handle, info: Handle) -> Handle {
    let result = std::panic::catch_unwind(|| {
        let mut count = 2; let mut args = [ptr::null_mut(); 2];
        if napi_get_cb_info(env, info, &mut count, args.as_mut_ptr(), ptr::null_mut(), ptr::null_mut()) != 0 || count != 2 { return Err("Expected source and language strings".into()); }
        extract(&js_string(env, args[0])?, &js_string(env, args[1])?)
    }).unwrap_or_else(|_| Err("Rust extractor panicked".into()));
    match result {
        Ok(text) => { let mut value = ptr::null_mut(); if napi_create_string_utf8(env, text.as_ptr().cast(), text.len(), &mut value) == 0 { value } else { ptr::null_mut() } }
        Err(message) => { let message = std::ffi::CString::new(message.replace('\0', " ")).unwrap(); napi_throw_error(env, ptr::null(), message.as_ptr()); ptr::null_mut() }
    }
}
#[no_mangle]
pub unsafe extern "C" fn napi_register_module_v1(env: Handle, exports: Handle) -> Handle {
    let mut function = ptr::null_mut();
    if napi_create_function(env, b"extract\0".as_ptr().cast(), 7, callback, ptr::null_mut(), &mut function) != 0 { return ptr::null_mut(); }
    if napi_set_named_property(env, exports, b"extract\0".as_ptr().cast(), function) != 0 { return ptr::null_mut(); }
    exports
}
