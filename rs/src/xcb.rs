pub struct XcbBackend {
    connection: xcb::Connection,
    root_window: xcb::x::Window,
    output_set_state: OutputSetState,
}

impl XcbBackend {
    pub fn start() -> Result<Self, anyhow::Error> {
        let (connection, screen_id) =
            xcb::Connection::connect_with_extensions(None, &[xcb::Extension::RandR], &[])?;
        let root_window = {
            let setup = connection.get_setup();
            let screen = setup
                .roots()
                .nth(screen_id.try_into()?)
                .ok_or_else(|| anyhow::Error::msg("bad preferred screen id"))?;
            screen.root()
        };

        let output_set_state = query_output_set_state(&connection, root_window)?;

        dbg!(&output_set_state.outputs);

        // Register for randr events
        let cookie = connection.send_request_checked(&xcb::randr::SelectInput {
            window: root_window,
            enable: xcb::randr::NotifyMask::SCREEN_CHANGE
                | xcb::randr::NotifyMask::CRTC_CHANGE
                | xcb::randr::NotifyMask::OUTPUT_CHANGE
                | xcb::randr::NotifyMask::OUTPUT_PROPERTY,
        });
        connection.check_request(cookie)?;

        Ok(XcbBackend {
            connection,
            root_window,
            output_set_state,
        })
    }
}

impl super::Backend for XcbBackend {
    fn wait_for_change(&mut self) -> Result<(), anyhow::Error> {
        loop {
            let mut had_randr_event = false;
            let event = self.connection.wait_for_event()?;
            had_randr_event |= check_randr_event(event);
            while let Some(event) = self.connection.poll_for_queued_event()? {
                had_randr_event |= check_randr_event(event)
            }
            if had_randr_event {
                break;
            }
        }
        Ok(())
    }
}

fn check_randr_event(event: xcb::Event) -> bool {
    match event {
        xcb::Event::RandR(e) => {
            match e {
                xcb::randr::Event::ScreenChangeNotify(e) => (),
                xcb::randr::Event::Notify(e) => (),
            }
            true
        }
        _ => false,
    }
}

#[derive(Debug)]
struct OutputSetState {
    screen_ressources: xcb::randr::GetScreenResourcesReply,
    crtcs: Vec<xcb::randr::GetCrtcInfoReply>,
    outputs: Vec<xcb::randr::GetOutputInfoReply>,
}

fn query_output_set_state(
    conn: &xcb::Connection,
    root_window: xcb::x::Window,
) -> Result<OutputSetState, xcb::Error> {
    let screen_ressources =
        conn.wait_for_reply(conn.send_request(&xcb::randr::GetScreenResources {
            window: root_window,
        }))?;
    let config_timestamp = screen_ressources.config_timestamp();

    let crtc_requests: Vec<xcb::randr::GetCrtcInfoCookie> = screen_ressources
        .crtcs()
        .iter()
        .cloned()
        .map(|crtc| {
            conn.send_request(&xcb::randr::GetCrtcInfo {
                crtc,
                config_timestamp,
            })
        })
        .collect();
    let output_requests: Vec<xcb::randr::GetOutputInfoCookie> = screen_ressources
        .outputs()
        .iter()
        .cloned()
        .map(|output| {
            conn.send_request(&xcb::randr::GetOutputInfo {
                output,
                config_timestamp,
            })
        })
        .collect();
    let crtcs = crtc_requests
        .into_iter()
        .map(|request| conn.wait_for_reply(request))
        .collect::<Result<Vec<_>, _>>()?;
    let outputs = output_requests
        .into_iter()
        .map(|request| conn.wait_for_reply(request))
        .collect::<Result<Vec<_>, _>>()?;

    Ok(OutputSetState {
        screen_ressources,
        crtcs,
        outputs,
    })
}
