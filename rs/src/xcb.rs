use crate::geometry::{Rotation, Transform};

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
            use xcb::Xid;
            match e {
                xcb::randr::Event::ScreenChangeNotify(e) => (),
                xcb::randr::Event::Notify(e) => match e.u() {
                    xcb::randr::NotifyData::Oc(e) => {
                        log::debug!(
                            "[event] OutputChange[{}] = {:?} {:?} crtc {}",
                            Xid::resource_id(&e.output()),
                            e.connection(),
                            Transform::from(e.rotation()),
                            Xid::resource_id(&e.crtc())
                        )
                    }
                    xcb::randr::NotifyData::Op(e) => {
                        log::debug!("[event] OutputProperty[{}]", Xid::resource_id(&e.output()))
                    }
                    _ => (),
                },
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
// TODO Edid query + generate Automatic layout

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

// xcb Rotation : apply reflect_x/y then a rotation. Stored as bitmask.
impl From<xcb::randr::Rotation> for Transform {
    // xcb representation is not unique, thus a conversion is needed.
    // conversion is applying transforms in sequence to an initially neutral Transform.
    fn from(r: xcb::randr::Rotation) -> Transform {
        use xcb::randr::Rotation as XcbT;
        let mut transform = Transform::default();
        if r.contains(XcbT::REFLECT_X) {
            transform = transform.reflect_x();
        }
        if r.contains(XcbT::REFLECT_Y) {
            transform = transform.reflect_y();
        }
        // theoretically all rotation flags could be present. ignore rot0 == noop.
        if r.contains(XcbT::ROTATE_90) {
            transform = transform.rotate(Rotation::R90);
        }
        if r.contains(XcbT::ROTATE_180) {
            transform = transform.rotate(Rotation::R180);
        }
        if r.contains(XcbT::ROTATE_270) {
            transform = transform.rotate(Rotation::R270);
        }
        transform
    }
}
impl From<Transform> for xcb::randr::Rotation {
    fn from(t: Transform) -> xcb::randr::Rotation {
        // The definition of xcb's transform has the same order as ours (reflect then rotation).
        // So we just need to translate the flags.
        use xcb::randr::Rotation as XcbT;
        let xcb_rotation = match t.rotation {
            Rotation::R0 => XcbT::ROTATE_0,
            Rotation::R90 => XcbT::ROTATE_90,
            Rotation::R180 => XcbT::ROTATE_180,
            Rotation::R270 => XcbT::ROTATE_270,
        };
        if t.reflect {
            xcb_rotation | XcbT::REFLECT_X
        } else {
            xcb_rotation
        }
    }
}
