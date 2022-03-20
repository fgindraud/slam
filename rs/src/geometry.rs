use std::ops::{Add, Div};

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

///////////////////////////////////////////////////////////////////////////////

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    LeftOf,
    RightOf,
    Above,
    Under,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Vec2d {
    pub x: isize,
    pub y: isize,
}

impl From<(isize, isize)> for Vec2d {
    fn from(pair: (isize, isize)) -> Vec2d {
        let (x, y) = pair;
        Vec2d { x, y }
    }
}

impl Add for Vec2d {
    type Output = Vec2d;
    fn add(self, rhs: Vec2d) -> Vec2d {
        Vec2d {
            x: self.x + rhs.x,
            y: self.y + rhs.y,
        }
    }
}

impl Div<isize> for Vec2d {
    type Output = Vec2d;
    fn div(self, d: isize) -> Vec2d {
        Vec2d {
            x: self.x / d,
            y: self.y / d,
        }
    }
}

/// `x` axis is from left to right. `y` axis is from bottom to top.
/// The rectangle covers pixels in `[bl.x, bl.x+size.x[ X [bl.y, bl.y+size.y[`.
/// Top and right sides are excluded.
pub struct Rect {
    pub bottom_left: Vec2d,
    pub size: Vec2d,
}

impl Rect {
    fn top_right(&self) -> Vec2d {
        self.bottom_left + self.size
    }
    fn bottom_right(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x, 0))
    }
    fn top_left(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((0, self.size.y))
    }

    fn center_bottom(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x / 2, 0))
    }
    fn center_top(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x / 2, self.size.y))
    }
    fn center_left(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((0, self.size.y / 2))
    }
    fn center_right(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x, self.size.y / 2))
    }
}

/// Determine if `lhs` is adjacent to `rhs`, and in which direction (`lhs direction rhs`).
/// Current criterion : adjacent == touching on one side with at least 1 pixel of frontier.
pub fn get_adjacent_direction(lhs: &Rect, rhs: &Rect) -> Option<Direction> {
    let size_average = (lhs.size + rhs.size) / 2;
    let is_adjacent_x = |l: Vec2d, r: Vec2d| l.x == r.x && (l.y - r.y).abs() <= size_average.y;
    let is_adjacent_y = |l: Vec2d, r: Vec2d| l.y == r.y && (l.x - r.x).abs() <= size_average.x;
    if is_adjacent_x(lhs.center_right(), rhs.center_left()) {
        return Some(Direction::LeftOf);
    }
    if is_adjacent_x(lhs.center_left(), rhs.center_right()) {
        return Some(Direction::RightOf);
    }
    if is_adjacent_y(lhs.center_top(), rhs.center_bottom()) {
        return Some(Direction::Under);
    }
    if is_adjacent_y(lhs.center_bottom(), rhs.center_top()) {
        return Some(Direction::Above);
    }
    None
}

#[cfg(test)]
#[test]
fn test_direction() {
    let size = Vec2d::from((1920, 1080));
    let primary = Rect {
        bottom_left: Vec2d::from((0, 0)),
        size,
    };
    let at_right = Rect {
        bottom_left: primary.bottom_right(),
        size,
    };
    let right_overlap = Rect {
        bottom_left: primary.bottom_right() + Vec2d::from((1, 0)),
        size,
    };
    let above_middle = Rect {
        bottom_left: primary.center_top(),
        size,
    };
    let smaller_below = Rect {
        bottom_left: primary.center_bottom() + Vec2d::from((200, -480)),
        size: Vec2d::from((640, 480)),
    };
    assert_eq!(get_adjacent_direction(&primary, &primary), None);
    assert_eq!(
        get_adjacent_direction(&primary, &at_right),
        Some(Direction::LeftOf)
    );
    assert_eq!(
        get_adjacent_direction(&at_right, &primary),
        Some(Direction::RightOf)
    );
    assert_eq!(get_adjacent_direction(&primary, &right_overlap), None);
    assert_eq!(
        get_adjacent_direction(&primary, &above_middle),
        Some(Direction::Under)
    );
    assert_eq!(
        get_adjacent_direction(&at_right, &above_middle),
        Some(Direction::Under)
    );
    assert_eq!(
        get_adjacent_direction(&primary, &smaller_below),
        Some(Direction::Above)
    );
    assert_eq!(get_adjacent_direction(&at_right, &smaller_below), None);
}