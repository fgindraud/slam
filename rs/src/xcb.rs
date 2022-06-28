use crate::geometry::{Rotation, Transform, Vec2di};
use crate::layout::{self, Edid};
use crate::Backend;
use std::collections::HashMap;
use std::time::Duration;
use xcb::Xid;

/// Backend for X server, using xcb bindings with randr extension.
/// Useful documentation : `/usr/share/doc/xorgproto/randrproto.txt`.
///
/// Uses the 1.3 and up way to layout multiple outputs.
/// This consists of mapping _outputs_ to viewports on the rectangle _screen_.
/// These outputs are mapped through _crtc_ that set _modeinfo_ and rotations.
///
/// Things that are not handled and assumed left default :
/// - homogeneous transform matrix on crtc : cool toy, but handling by window managers is mostly broken.
/// - rotations at the screen level : legacy, superseeded by current mode.
/// - any recent provider stuff.
pub struct XcbBackend {
    connection: xcb::Connection,
    root_window: xcb::x::Window,
    edid_atom: xcb::x::Atom,
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

        let output_set_state = OutputSetState::query(&connection, root_window, edid_atom)?;
        Ok(XcbBackend {
            connection,
            root_window,
            edid_atom,
            output_set_state,
        })
    }
}

impl Backend for XcbBackend {
    fn current_layout(&self) -> layout::Layout {
        convert_to_layout(&self.output_set_state)
    }

    fn wait_for_change(&mut self, reaction_delay: Option<Duration>) -> Result<(), anyhow::Error> {
        // Wait for any randr event, then reload entire randr state.
        // Easier than patching state with notify event data.
        loop {
            // Wait for event, flush all events, and determine if it was randr related
            let mut had_randr_event = false;
            let event = self.connection.wait_for_event()?;
            had_randr_event |= check_randr_event(event);
            while let Some(event) = self.connection.poll_for_queued_event()? {
                had_randr_event |= check_randr_event(event)
            }
            if had_randr_event {
                // If delay is requested, also flush all randr events during the delay
                if let Some(delay) = reaction_delay {
                    std::thread::sleep(delay);
                    if let Some(event) = self.connection.poll_for_event()? {
                        check_randr_event(event);
                    }
                    while let Some(event) = self.connection.poll_for_queued_event()? {
                        check_randr_event(event);
                    }
                }
                self.output_set_state =
                    OutputSetState::query(&self.connection, self.root_window, self.edid_atom)?;
                return Ok(());
            }
        }
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

impl OutputSetState {
    fn query(
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

        let crtc_requests = Vec::from_iter(ressources.crtcs().iter().map(make_crtc_request));
        let output_requests = Vec::from_iter(ressources.outputs().iter().map(make_output_requests));
        let crtcs = Result::from_iter(crtc_requests.into_iter().map(process_crtc_reply))?;
        let outputs = Result::from_iter(output_requests.into_iter().map(process_output_replies))?;

        Ok(OutputSetState {
            ressources,
            crtcs,
            outputs,
        })
    }

    fn mode_from_id(&self, id: xcb::randr::Mode) -> Option<layout::Mode> {
        if id.is_none() {
            return None;
        }
        self.ressources
            .modes()
            .into_iter()
            .find(|m| m.id == id.resource_id())
            .map(|m| layout::Mode::from(m))
    }
}

impl OutputState {
    /// Consider an output connected only if really usable : has crtcs, modes.
    fn is_connected(&self) -> bool {
        self.info.connection() == xcb::randr::Connection::Connected
            && self.info.modes().len() > 0
            && self.info.crtcs().len() > 0
    }
}

///////////////////////////////////////////////////////////////////////////////

fn convert_to_layout(output_states: &OutputSetState) -> layout::Layout {
    // Get output information after checking that it is properly enabled (crtc + mode).
    let convert_output_state = |xcb_state: &OutputState| -> layout::OutputState {
        let assigned_crtc = match output_states.crtcs.get(&xcb_state.info.crtc()) {
            Some(crtc) => crtc,
            None => return layout::OutputState::Disabled,
        };
        let valid_mode = match output_states.mode_from_id(assigned_crtc.mode()) {
            Some(mode) => mode,
            None => return layout::OutputState::Disabled,
        };
        layout::OutputState::Enabled {
            mode: valid_mode,
            transform: Transform::from(assigned_crtc.rotation()),
            bottom_left: Vec2di::new(assigned_crtc.x().into(), assigned_crtc.y().into()),
        }
    };
    output_states
        .outputs
        .values()
        .filter(|state| state.is_connected())
        .map(|state| layout::OutputEntry {
            id: match state.edid {
                Some(edid) => layout::OutputId::Edid(edid),
                None => layout::OutputId::Name(state.name.clone()),
            },
            state: convert_output_state(state),
        })
        .collect()
}

///////////////////////////////////////////////////////////////////////////////

/// xcb Rotation : apply reflect_x/y then a rotation. Stored as bitmask.
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

impl From<&'_ xcb::randr::ModeInfo> for layout::Mode {
    fn from(xcb_mode: &'_ xcb::randr::ModeInfo) -> layout::Mode {
        let size = Vec2di::new(xcb_mode.width.into(), xcb_mode.height.into());
        let dots = u32::from(xcb_mode.htotal) * u32::from(xcb_mode.vtotal);
        assert_ne!(dots, 0, "invalid xcb::ModeInfo");
        let frequency = f64::from(xcb_mode.dot_clock) / f64::from(dots);
        layout::Mode { size, frequency }
    }
}
