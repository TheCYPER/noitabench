//! `Game::burning_rect`: the read-only fire mask a viewer draws.

mod scene;

use scene::*;

#[test]
fn burning_rect_marks_the_burning_cells_row_major() {
    let mut g = world(60, 40, 5, 1);
    g.world_mut().fill_rect(10, 10, 5, 1, "wood").unwrap();
    assert!(g.world_mut().ignite(11, 10));
    assert!(g.world_mut().ignite(13, 10));
    // x 8..16, y 9..12: the wood row is the second row of the window
    let mask = g.burning_rect(8, 9, 8, 3);
    assert_eq!(mask.len(), 24);
    let lit: Vec<usize> = (0..mask.len()).filter(|&i| mask[i] == 1).collect();
    assert_eq!(lit, vec![8 + 3, 8 + 5]);
    assert!(mask.iter().all(|&b| b <= 1));
}

#[test]
fn burning_rect_is_zero_outside_the_world_and_for_empty_rectangles() {
    let mut g = world(60, 40, 5, 1);
    g.world_mut().fill_rect(0, 10, 3, 1, "wood").unwrap();
    assert!(g.world_mut().ignite(0, 10));
    // a window that hangs over the left edge: only the cell at x = 0 burns
    let mask = g.burning_rect(-2, 10, 5, 1);
    assert_eq!(mask, vec![0, 0, 1, 0, 0]);
    assert!(g.burning_rect(0, 0, 0, 5).is_empty());
    assert!(g.burning_rect(0, 0, -3, 5).is_empty());
    // far outside: right size, no fire
    assert_eq!(g.burning_rect(1000, 1000, 4, 2), vec![0; 8]);
}

#[test]
fn burning_rect_follows_the_fire_as_it_burns_out() {
    let mut g = world(60, 40, 5, 1);
    g.world_mut().fill_rect(10, 10, 3, 1, "wood").unwrap();
    assert!(g.world_mut().ignite(11, 10));
    assert_eq!(g.burning_rect(11, 10, 1, 1), vec![1]);
    run(&mut g, 1500, &cogbench_game::Controls::default());
    assert!(
        g.burning_rect(0, 0, 60, 40).iter().all(|&b| b == 0),
        "everything burned out or stopped"
    );
}

#[test]
fn burning_rect_always_has_w_times_h_bytes_even_at_the_edge_of_the_integers() {
    let g = world(60, 40, 5, 1);
    // a rectangle that runs past i32::MAX still answers one byte per cell, all of them dark
    assert_eq!(g.burning_rect(i32::MAX - 1, 3, 5, 2), vec![0; 10]);
    assert_eq!(g.burning_rect(3, i32::MAX - 2, 2, 6), vec![0; 12]);
    assert_eq!(g.burning_rect(i32::MIN, i32::MIN, 3, 3), vec![0; 9]);
}
