use crate::geometry::{Rotation, Transform};
use crate::layout::Edid;
use std::collections::HashMap;

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

        // Register for randr events
        connection.send_and_check_request(&xcb::randr::SelectInput {
            window: root_window,
            enable: xcb::randr::NotifyMask::SCREEN_CHANGE
                | xcb::randr::NotifyMask::CRTC_CHANGE
                | xcb::randr::NotifyMask::OUTPUT_CHANGE
                | xcb::randr::NotifyMask::OUTPUT_PROPERTY,
        })?;

        let edid_atom = {
            let cookie = connection.send_request(&xcb::x::InternAtom {
                only_if_exists: true,
                name: b"EDID",
            });
            let reply = connection.wait_for_reply(cookie)?;
            match reply.atom() {
                xcb::x::ATOM_NONE => {
                    return Err(anyhow::Error::msg("Edid not defined by X server"))
                }
                atom => atom,
            }
        };

        let output_set_state = query_output_set_state(&connection, root_window, edid_atom)?;
        dbg!(&output_set_state.outputs);

        Ok(XcbBackend {
            connection,
            root_window,
            output_set_state,
        })
    }
}

impl super::Backend for XcbBackend {
    fn wait_for_change(&mut self) -> Result<(), anyhow::Error> {
        // Wait for any randr event, then reload entire randr state.
        // Easier than patching state with notify event data.
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
            log::debug!("[event] {:?}", e);
            true
        }
        _ => false,
    }
}

///////////////////////////////////////////////////////////////////////////////

#[derive(Debug)]
struct OutputSetState {
    ressources: xcb::randr::GetScreenResourcesReply,
    crtcs: HashMap<xcb::randr::Crtc, xcb::randr::GetCrtcInfoReply>,
    outputs: HashMap<xcb::randr::Output, OutputState>,
}
#[derive(Debug)]
struct OutputState {
    info: xcb::randr::GetOutputInfoReply,
    name: String,
    edid: Option<Edid>,
}

fn query_output_set_state(
    conn: &xcb::Connection,
    root_window: xcb::x::Window,
    edid_atom: xcb::x::Atom,
) -> Result<OutputSetState, anyhow::Error> {
    // Some replies have an additional status field.
    // These bad status codes never happened in the read state part so treat them as errors.
    fn check_status(status: xcb::randr::SetConfig) -> Result<(), anyhow::Error> {
        use xcb::randr::SetConfig::*;
        match status {
            Success => Ok(()),
            InvalidConfigTime => Err(anyhow::Error::msg("SetConfig::InvalidConfigTime")),
            InvalidTime => Err(anyhow::Error::msg("SetConfig::InvalidTime")),
            Failed => Err(anyhow::Error::msg("SetConfig::Failed")),
        }
    }

    // Screen ressources must be done first, as it gives timestamps and output/crtc ids required for other requests.
    let ressources_req = conn.send_request(&xcb::randr::GetScreenResources {
        window: root_window,
    });
    let ressources = conn.wait_for_reply(ressources_req)?;
    let config_timestamp = ressources.config_timestamp();

    // Request info from all Crtc and outputs in parallel.
    let make_crtc_request = |&crtc| {
        let req = conn.send_request(&xcb::randr::GetCrtcInfo {
            crtc,
            config_timestamp,
        });
        (crtc, req)
    };
    let process_crtc_reply = |(crtc, request)| -> Result<_, anyhow::Error> {
        let reply: xcb::randr::GetCrtcInfoReply = conn.wait_for_reply(request)?;
        check_status(reply.status())?;
        Ok((crtc, reply))
    };

    let make_output_requests = |&output| {
        let info_req = conn.send_request(&xcb::randr::GetOutputInfo {
            output,
            config_timestamp,
        });
        let edid_req = conn.send_request(&xcb::randr::GetOutputProperty {
            output,
            property: edid_atom,
            r#type: xcb::x::GETPROPERTYTYPE_ANY,
            long_offset: 0,
            long_length: 128, // No need for more than 128 bytes
            delete: false,
            pending: false,
        });
        (output, info_req, edid_req)
    };
    let process_output_replies = |(output, info_req, edid_req)| -> Result<_, anyhow::Error> {
        let info: xcb::randr::GetOutputInfoReply = conn.wait_for_reply(info_req)?;
        check_status(info.status())?;
        let name = String::from_utf8_lossy(info.name()).to_string();
        let edid_reply: xcb::randr::GetOutputPropertyReply = conn.wait_for_reply(edid_req)?;
        let edid = match edid_reply.r#type() {
            xcb::x::ATOM_INTEGER => match Edid::try_from(edid_reply.data()) {
                Ok(edid) => Some(edid),
                Err(e) => {
                    log::debug!("{}: {}", name, e);
                    None
                }
            },
            xcb::x::ATOM_NONE => None,
            atom => {
                let atom_name_req = conn.send_request(&xcb::x::GetAtomName { atom });
                let atom_name_reply = conn.wait_for_reply(atom_name_req)?;
                let atom_name = atom_name_reply.name();
                log::debug!("{}: unexpected type for Edid: {}", name, atom_name);
                None
            }
        };
        let state = OutputState { info, name, edid };
        Ok((output, state))
    };

    let crtc_requests = ressources
        .crtcs()
        .iter()
        .map(make_crtc_request)
        .collect::<Vec<_>>();
    let output_requests = ressources
        .outputs()
        .iter()
        .map(make_output_requests)
        .collect::<Vec<_>>();
    let crtcs = crtc_requests
        .into_iter()
        .map(process_crtc_reply)
        .collect::<Result<HashMap<_, _>, anyhow::Error>>()?;
    let outputs = output_requests
        .into_iter()
        .map(process_output_replies)
        .collect::<Result<HashMap<_, _>, anyhow::Error>>()?;

    Ok(OutputSetState {
        ressources,
        crtcs,
        outputs,
    })
}

///////////////////////////////////////////////////////////////////////////////

// TODO generate Automatic layout

///////////////////////////////////////////////////////////////////////////////

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
