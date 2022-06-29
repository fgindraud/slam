use crate::relation::InvertibleRelation;
use std::ops::{Add, Sub, SubAssign};

/// Trigonometric orientation (anti-clockwise)
#[derive(Clone, Copy, PartialEq, Eq, serde::Serialize)]
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
#[derive(Clone, Default, PartialEq, Eq, serde::Serialize)]
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

/// Tag for relative positionning of monitor outputs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    LeftOf,
    RightOf,
    Above,
    Under,
}

impl InvertibleRelation for Direction {
    fn inverse(&self) -> Direction {
        match self {
            Direction::LeftOf => Direction::RightOf,
            Direction::RightOf => Direction::LeftOf,
            Direction::Above => Direction::Under,
            Direction::Under => Direction::Above,
        }
    }
}

///////////////////////////////////////////////////////////////////////////////

/// Pair of integer, used as coordinates / size. Uses the usual cartesian orientation :
/// - `x` goes from right to left.
/// - `y` goes upward.
pub type Vec2di = Vec2d<i32>;

/// Generic pair type. Specialised for coordinates as [`Vec2di`].
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, serde::Serialize)]
pub struct Vec2d<T> {
    pub x: T,
    pub y: T,
}

impl<T> Vec2d<T> {
    pub fn new(x: T, y: T) -> Self {
        Vec2d { x, y }
    }

    pub fn apply(self, transform: &Transform) -> Vec2d<T> {
        match transform.are_axis_swapped() {
            false => self,
            true => Vec2d::new(self.y, self.x),
        }
    }
}

impl<T> From<(T, T)> for Vec2d<T> {
    fn from(pair: (T, T)) -> Self {
        Vec2d {
            x: pair.0,
            y: pair.1,
        }
    }
}

impl<T: Add> Add for Vec2d<T> {
    type Output = Vec2d<T::Output>;
    fn add(self, rhs: Vec2d<T>) -> Self::Output {
        Vec2d {
            x: self.x + rhs.x,
            y: self.y + rhs.y,
        }
    }
}

impl<T: Sub> Sub for Vec2d<T> {
    type Output = Vec2d<T::Output>;
    fn sub(self, rhs: Vec2d<T>) -> Self::Output {
        Vec2d {
            x: self.x - rhs.x,
            y: self.y - rhs.y,
        }
    }
}

impl<T: SubAssign> SubAssign for Vec2d<T> {
    fn sub_assign(&mut self, rhs: Vec2d<T>) {
        self.x -= rhs.x;
        self.y -= rhs.y
    }
}

impl<T: Ord> Vec2d<T> {
    /// Component-wise min
    pub fn cwise_min(self, rhs: Vec2d<T>) -> Vec2d<T> {
        Vec2d {
            x: std::cmp::min(self.x, rhs.x),
            y: std::cmp::min(self.y, rhs.y),
        }
    }
    /// Component-wise max.
    fn cwise_max(self, rhs: Vec2d<T>) -> Vec2d<T> {
        Vec2d {
            x: std::cmp::max(self.x, rhs.x),
            y: std::cmp::max(self.y, rhs.y),
        }
    }
}

///////////////////////////////////////////////////////////////////////////////

/// `x` axis is from left to right. `y` axis is from bottom to top.
/// The rectangle covers pixels in `[bl.x, bl.x+size.x[ X [bl.y, bl.y+size.y[`.
/// Top and right sides are excluded.
#[derive(Debug, Clone)]
pub struct Rect {
    pub bottom_left: Vec2di,
    pub size: Vec2di,
}

impl Rect {
    pub fn top_right(&self) -> Vec2di {
        self.bottom_left + self.size
    }
    fn bottom_right(&self) -> Vec2di {
        self.bottom_left + Vec2di::new(self.size.x, 0)
    }
    fn top_left(&self) -> Vec2di {
        self.bottom_left + Vec2di::new(0, self.size.y)
    }

    fn center_bottom(&self) -> Vec2di {
        self.bottom_left + Vec2di::new(self.size.x / 2, 0)
    }
    fn center_top(&self) -> Vec2di {
        self.bottom_left + Vec2di::new(self.size.x / 2, self.size.y)
    }
    fn center_left(&self) -> Vec2di {
        self.bottom_left + Vec2di::new(0, self.size.y / 2)
    }
    fn center_right(&self) -> Vec2di {
        self.bottom_left + Vec2di::new(self.size.x, self.size.y / 2)
    }

    fn offset(&self, delta: Vec2di) -> Rect {
        Rect {
            bottom_left: self.bottom_left + delta,
            size: self.size,
        }
    }

    /// Does `self` overlaps `other` ?
    pub fn overlaps(&self, other: &Rect) -> bool {
        // It is easier to determine if there is NO overlap : the other rect must be entirely on one side.
        let left_of = self.bottom_right().x <= other.bottom_left.x;
        let right_of = other.bottom_right().x <= self.bottom_left.x;
        let under = self.top_left().y <= other.bottom_left.y;
        let above = other.top_left().y <= self.bottom_left.y;
        let no_overlap = left_of || right_of || under || above;
        !no_overlap
    }

    /// Determine if `lhs` is adjacent to `rhs`, and in which direction (`lhs direction rhs`).
    /// Current criterion : adjacent == touching on one side with an overlap at least half the size of the smallest rect.
    pub fn adjacent_direction(&self, rhs: &Rect) -> Option<Direction> {
        let lhs = self;
        let size_max = Vec2di::cwise_max(lhs.size, rhs.size);
        let is_adjacent_x =
            |l: Vec2di, r: Vec2di| l.x == r.x && 2 * (l.y - r.y).abs() <= size_max.y;
        let is_adjacent_y =
            |l: Vec2di, r: Vec2di| l.y == r.y && 2 * (l.x - r.x).abs() <= size_max.x;
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
}

#[cfg(test)]
#[test]
fn test_overlaps() {
    let main = Rect {
        bottom_left: Vec2di::new(0, 0),
        size: Vec2di::new(1920, 1080),
    };
    // Adjacent
    assert!(!main.overlaps(&main.offset((1920, 0).into())));
    assert!(!main.overlaps(&main.offset((-1920, 0).into())));
    assert!(!main.overlaps(&main.offset((0, 1080).into())));
    assert!(!main.overlaps(&main.offset((0, -1080).into())));
    // Adjacent to corners
    assert!(!main.overlaps(&main.offset((1920, 600).into())));
    assert!(!main.overlaps(&main.offset((1920, 1080).into())));
    // With gap
    assert!(!main.overlaps(&main.offset((-2000, 0).into())));
    assert!(!main.overlaps(&main.offset((2000, 0).into())));
    assert!(!main.overlaps(&main.offset((0, 1500).into())));
    // Should overlap
    assert!(main.overlaps(&main.offset((1919, 0).into())));
    assert!(main.overlaps(&main.offset((-1919, 0).into())));
    assert!(main.overlaps(&main.offset((200, 0).into())));
    assert!(main.overlaps(&main.offset((0, 1079).into())));
    assert!(main.overlaps(&main))
}

#[cfg(test)]
#[test]
fn test_direction() {
    let size = Vec2di::new(1920, 1080);
    let primary = Rect {
        bottom_left: Vec2di::new(0, 0),
        size,
    };
    let at_right = Rect {
        bottom_left: primary.bottom_right(),
        size,
    };
    let right_overlap = Rect {
        bottom_left: primary.bottom_right() + Vec2di::new(1, 0),
        size,
    };
    let above_middle = Rect {
        bottom_left: primary.center_top(),
        size,
    };
    let smaller_below = Rect {
        bottom_left: primary.center_bottom() + Vec2di::new(200, -480),
        size: Vec2d::new(640, 480),
    };
    assert_eq!(Rect::adjacent_direction(&primary, &primary), None);
    assert_eq!(
        Rect::adjacent_direction(&primary, &at_right),
        Some(Direction::LeftOf)
    );
    assert_eq!(
        Rect::adjacent_direction(&at_right, &primary),
        Some(Direction::RightOf)
    );
    assert_eq!(Rect::adjacent_direction(&primary, &right_overlap), None);
    assert_eq!(
        Rect::adjacent_direction(&primary, &above_middle),
        Some(Direction::Under)
    );
    assert_eq!(
        Rect::adjacent_direction(&at_right, &above_middle),
        Some(Direction::Under)
    );
    assert_eq!(
        Rect::adjacent_direction(&primary, &smaller_below),
        Some(Direction::Above)
    );
    assert_eq!(Rect::adjacent_direction(&at_right, &smaller_below), None);
}
