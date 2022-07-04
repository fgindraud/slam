use anyhow::Context;

use crate::layout::Layout;
use std::collections::HashSet;
use std::hash::Hash;
use std::path::PathBuf;

/// Provide [`Eq`]+[`Hash`] on the sorted ids of layout.
/// [`serde_json`] flattens *newtypes* so this layer has no impact on serialization format.
#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct LayoutById(Layout);

impl PartialEq for LayoutById {
    fn eq(&self, other: &Self) -> bool {
        Iterator::eq(self.0.connected_outputs(), other.0.connected_outputs())
    }
}
impl Eq for LayoutById {}

impl Hash for LayoutById {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        for id in self.0.connected_outputs() {
            id.hash(state)
        }
    }
}

pub struct Database {
    layouts: HashSet<LayoutById>,
    path: PathBuf,
}

impl Database {
    /// Load database from file, or use an empty one if it cannot be read.
    /// Only generate an error if the database is invalid / corrupted.
    pub fn load_or_empty(path: PathBuf) -> Result<Database, anyhow::Error> {
        let layouts = match std::fs::read(&path) {
            Ok(file_content) => serde_json::from_slice(&file_content)
                .with_context(|| format!("error parsing database {}", path.display()))?,
            Err(e) => {
                log::warn!(
                    "cannot read database {}: {} ; using an empty database instead",
                    path.display(),
                    e
                );
                HashSet::new()
            }
        };
        Ok(Database { layouts, path })
    }
}
