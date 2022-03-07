pub struct XcbBackend {
    connection: xcb::Connection,
}

impl XcbBackend {
    pub fn start() -> Result<Self, anyhow::Error> {
        let (connection, screen_id) =
            xcb::Connection::connect_with_extensions(None, &[xcb::Extension::RandR], &[])?;
        Ok(XcbBackend { connection })
    }
}

impl super::Backend for XcbBackend {}
