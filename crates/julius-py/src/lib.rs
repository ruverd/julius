use pyo3::prelude::*;

#[pyfunction]
fn compress_repeated_lines(content: &str, artifact_id: &str) -> String {
    julius_core::compress_repeated_lines(content, artifact_id)
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(compress_repeated_lines, module)?)?;
    Ok(())
}
