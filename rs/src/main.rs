use clap::Parser;
use std::path::PathBuf;

#[derive(Debug, Parser)]
#[clap(version, about)]
struct DaemonOptions {
    /// Path to database file (default: <sys_config_dir>/slam/database.json)
    #[clap(long, parse(from_os_str), value_name = "FILE")]
    database: Option<PathBuf>,

    /// Sets log level: error warn info debug trace
    #[clap(long, value_name = "LEVEL")]
    log_level: Option<log::Level>,
}

fn main() -> Result<(), anyhow::Error> {
    let options = DaemonOptions::parse();

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
    match slam::xcb::XcbBackend::start() {
        Ok(mut backend) => return run_daemon(&mut backend),
        Err(err) => eprintln!("Cannot start Xcb backend: {}", err),
    }
    Err(anyhow::Error::msg("No working available backend"))
}

fn run_daemon(backend: &mut dyn slam::Backend) -> Result<(), anyhow::Error> {
    loop {
        backend.wait_for_change()?
    }
}
