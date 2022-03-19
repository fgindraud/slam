#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Rotation {
    R0 = 0,
    R90 = 1,
    R180 = 2,
    R270 = 3,
}

impl std::fmt::Debug for Rotation {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        ((*self as isize) * 90).fmt(f)
    }
}
impl Default for Rotation {
    fn default() -> Rotation {
        Rotation::R0
    }
}
impl Rotation {
    fn rotate(&self, r: Rotation) -> Rotation {
        // Using mod 4 arithmetic for efficiency
        let cumulated_rot = *self as usize + r as usize;
        match cumulated_rot % 4 {
            0 => Rotation::R0,
            1 => Rotation::R90,
            2 => Rotation::R180,
            3 => Rotation::R270,
            _ => unreachable!(),
        }
    }
}

/// Transformation type with unique representation for all screen 90° rotations and x/y reflects.
/// Internally this is a reflect along X coordinates followed by the rotation (trigonometric).
#[derive(Clone, Default, PartialEq, Eq)]
pub struct Transform {
    pub reflect: bool,
    pub rotation: Rotation,
}

impl std::fmt::Debug for Transform {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        let prefix = if self.reflect { "R" } else { "" };
        write!(f, "{}{:?}", prefix, self.rotation)
    }
}

impl Transform {
    pub fn are_axis_swapped(&self) -> bool {
        match self.rotation {
            Rotation::R0 | Rotation::R180 => false,
            Rotation::R90 | Rotation::R270 => true,
        }
    }

    /// Apply a rotation after the current transform
    pub fn rotate(&self, r: Rotation) -> Transform {
        Transform {
            reflect: self.reflect,
            rotation: self.rotation.rotate(r),
        }
    }

    /// Apply a reflection along x axis after the current transform
    pub fn reflect_x(&self) -> Transform {
        Transform {
            reflect: std::ops::Not::not(self.reflect),
            rotation: match self.rotation {
                Rotation::R0 => Rotation::R0,
                Rotation::R90 => Rotation::R270,
                Rotation::R180 => Rotation::R180,
                Rotation::R270 => Rotation::R90,
            },
        }
    }

    /// Apply a reflection along y axis after the current transform
    pub fn reflect_y(&self) -> Transform {
        Transform {
            reflect: std::ops::Not::not(self.reflect),
            rotation: match self.rotation {
                Rotation::R0 => Rotation::R180,
                Rotation::R90 => Rotation::R90,
                Rotation::R180 => Rotation::R0,
                Rotation::R270 => Rotation::R270,
            },
        }
    }
}

#[cfg(test)]
#[test]
fn test_transform() {
    assert_eq!(Rotation::R0, Rotation::R270.rotate(Rotation::R90));
    assert_eq!(Rotation::R180, Rotation::R270.rotate(Rotation::R270));
    assert_eq!(
        Transform::default().rotate(Rotation::R180),
        Transform::default().reflect_x().reflect_y()
    );
    assert_eq!(
        Transform::default().rotate(Rotation::R90).reflect_y(),
        Transform::default().rotate(Rotation::R270).reflect_x()
    );
}
