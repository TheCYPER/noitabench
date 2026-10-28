import { parseProfile } from '../js/report/profile.js';
import { fixtureJson } from './helpers.js';

/** The JSON of a profile fixture: `bot`, `agent` or `human` (cut from real runs by make_profile_fixtures.py). */
export const raw = (name) => fixtureJson('profiles', `${name}.profile.json`);
/** The fixture as the page reads it. */
export const load = (name) => parseProfile(raw(name), `${name}.profile.json`);
/** The made-up seeds written into the fixtures: they must appear nowhere on a page. */
export const SEEDS = ['424242', '717171'];
