use gumdrop::Options;
use std::path::PathBuf;

mod geometry;
mod layout;

trait Backend {
    fn wait_for_change(&mut self) -> Result<(), anyhow::Error>;
}

#[cfg(feature = "xcb")]
mod xcb;

#[derive(Debug, Options)]
struct DaemonOptions {
    help: bool,

    #[options(help = "path to database file (default: <system_config_dir>/slam/database.json)")]
    database: Option<PathBuf>,

    #[options(help = "sets log level: error warn info debug trace", meta = "LEVEL")]
    log_level: Option<log::Level>,
}

fn main() -> Result<(), anyhow::Error> {
    let options = DaemonOptions::parse_args_default_or_exit();

    simple_logger::init_with_level(options.log_level.unwrap_or(log::Level::Warn))?;

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

    dbg!(database_path);

    #[cfg(feature = "xcb")]
    match xcb::XcbBackend::start() {
        Ok(mut backend) => return run_daemon(&mut backend),
        Err(err) => eprintln!("Cannot start Xcb backend: {}", err),
    }
    Err(anyhow::Error::msg("No working available backend"))
}

fn run_daemon(backend: &mut dyn Backend) -> Result<(), anyhow::Error> {
    loop {
        backend.wait_for_change()?
    }
}
