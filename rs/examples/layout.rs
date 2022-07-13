#![allow(dead_code)] // Testing only part of the code.

use slam::geometry::{Rect, Vec2d};

// Palette with evenly distributed hues
fn color_palette(n: usize) -> impl Iterator<Item = tiny_skia::Color> {
    use palette::*;
    let n = u8::try_from(n).expect("too many colors");
    let red: Srgb<f32> = named::RED.into_format();
    let red = Hsl::from_color(red);
    (0..n).map(move |i| {
        let shift_frac = f32::from(i) / f32::from(n);
        let color: Hsl = red.shift_hue(360. * shift_frac);
        let color: Srgb<f32> = color.into_color();
        tiny_skia::Color::from_rgba(color.red, color.green, color.blue, 1.).unwrap()
    })
}

fn boundary_rect(rects: &[Rect]) -> Rect {
    assert!(!rects.is_empty());
    let bottom_left = Vec2d {
        x: rects.iter().map(|r| r.bottom_left.x).min().unwrap(),
        y: rects.iter().map(|r| r.bottom_left.y).min().unwrap(),
    };
    let top_right = Vec2d {
        x: rects.iter().map(|r| r.top_right().x).max().unwrap(),
        y: rects.iter().map(|r| r.top_right().y).max().unwrap(),
    };
    Rect {
        bottom_left,
        size: (top_right - bottom_left).map(|i| i as u32),
    }
}

fn draw_layout(png_path: &std::path::Path, rects: &[Rect]) {
    // rects coordinates are arbitray, find enclosing rect where drawing is done
    let boundary = boundary_rect(rects);
    let mut image = tiny_skia::Pixmap::new(boundary.size.x, boundary.size.y).unwrap();
    // skia has y axis downwards, fix that
    let transform =
        tiny_skia::Transform::from_scale(1., -1.).post_translate(0., boundary.size.y as f32);
    // draw rectangles
    for (rect, color) in Iterator::zip(rects.into_iter(), color_palette(rects.len())) {
        let bl_in_boundary_ref = rect.bottom_left - boundary.bottom_left;
        let rect = tiny_skia::Rect::from_xywh(
            bl_in_boundary_ref.x as f32,
            bl_in_boundary_ref.y as f32,
            rect.size.x as f32,
            rect.size.y as f32,
        )
        .unwrap();
        let mut paint = tiny_skia::Paint::default();
        paint.set_color(color);
        image.fill_rect(rect, &paint, transform, None).unwrap();
    }
    image.save_png(png_path).unwrap()
}

fn main() {
    let rects = [
        Rect {
            bottom_left: Vec2d::default(),
            size: Vec2d::new(640, 480),
        },
        Rect {
            bottom_left: Vec2d::new(640, 0),
            size: Vec2d::new(320, 240),
        },
    ];
    draw_layout(std::path::Path::new("static.png"), &rects);
}
