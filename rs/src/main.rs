use gumdrop::Options;
use std::path::PathBuf;

trait Backend {
    //
}

#[cfg(feature = "xcb")]
mod xcb;

fn start_backend() -> Option<Box<dyn Backend>> {
    #[cfg(feature = "xcb")]
    return Some(Box::new(xcb::XcbBackend));
    None
}

#[derive(Debug, Options)]
struct DaemonOptions {
    help: bool,

    #[options(help = "path to database file (default: <system_config_dir>/slam/database.json)")]
    database: Option<PathBuf>,
}

fn main() -> Result<(), anyhow::Error> {
    let options = DaemonOptions::parse_args_default_or_exit();

    let database_path = match options.database {
        Some(path) => path,
        None => {
            let mut p = dirs::config_dir().ok_or(anyhow::Error::msg(
                "no system config directory, database path must be provided",
            ))?;
            p.push("slam");
            p.push("database.json");
            p
        }
    };

    let backend = start_backend();

    dbg!(database_path, backend.is_some());

    Ok(())
}
