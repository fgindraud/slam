use crate::layout::Layout;
use anyhow::Context;
use std::collections::HashSet;
use std::io::BufWriter;
use std::path::PathBuf;

/// Provide [`Eq`]+[`std::hash::Hash`] on the sorted ids of layout.
/// [`serde_json`] flattens *newtypes* so this layer has no impact on serialization format.
#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub struct LayoutById(pub Layout);

impl PartialEq for LayoutById {
    fn eq(&self, other: &Self) -> bool {
        Iterator::eq(self.0.connected_outputs(), other.0.connected_outputs())
    }
}
impl Eq for LayoutById {}
impl std::hash::Hash for LayoutById {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        for id in self.0.connected_outputs() {
            id.hash(state)
        }
    }
}

/// Database of known layouts, stored in memory with a file backing using [`serde_json`].
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

    /// Store a layout, and update the file database.
    /// To avoid breaking an existing database if the serialization fails in the middle,
    /// the database is serialized to a temporary file, then moved on success.
    pub fn store_layout(&mut self, layout: Layout) -> Result<(), anyhow::Error> {
        self.layouts.replace(LayoutById(layout));
        // Write db to tmp file
        let mut tmp_path = self.path.clone();
        tmp_path.set_extension("json.tmp"); // same dir, just change extension
        if let Some(parent) = tmp_path.parent() {
            std::fs::create_dir_all(parent).with_context(|| {
                format!(
                    "cannot create parent directories of database file {}",
                    tmp_path.display()
                )
            })?
        }
        let tmp_file = std::fs::File::create(&tmp_path).with_context(|| {
            format!("cannot open temporary database file {}", tmp_path.display())
        })?;
        serde_json::to_writer(BufWriter::new(tmp_file), &self.layouts)
            .with_context(|| format!("cannot write database to {}", tmp_path.display()))?;
        // On success, atomically replace existing db with new one
        std::fs::rename(&tmp_path, &self.path).with_context(|| {
            format!(
                "failed to replace database {} with temporary {}",
                self.path.display(),
                tmp_path.display()
            )
        })
    }

    /// Get stored layout for given output ids.
    /// 
    /// It does not seem possible to use the alternate key type mode as [`std::borrow::Borrow`] returns a reference to an existing object.
    /// To represent the set of connected outputs in non copy mode we need a reference struct (iterator, etc).
    pub fn get_layout<'db>(&'db self, output_ids: &LayoutById) -> Option<&'db Layout> {
        self.layouts.get(output_ids).map(|l| &l.0)
    }
}
