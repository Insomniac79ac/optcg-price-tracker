/** Display names from the existing official Bandai Asia-English catalogue
 * snapshot (2026-08-26), data/official_snapshots/bandai_asia_en/current/series.jsonl.
 * Source: https://asia-en.onepiece-cardgame.com/cardlist/
 * Only product-type wrappers and trailing [codes] were removed; ROMANCE DAWN
 * uses title case. These labels never determine membership or destinations.
 * The current Home catalogue contract exposes codes, not product names, so
 * this small reference avoids an additional request. Prefer a supplied name
 * whenever a caller already has one; unknown codes get no invented title.
 */
const OFFICIAL_RELEASE_NAMES: Readonly<Record<string, string>> = {
  "PRB-02": "ONE PIECE CARD THE BEST vol.2",
  "PRB-01": "ONE PIECE CARD THE BEST",
  "EB-04": "EGGHEAD CRISIS",
  "EB-03": "ONE PIECE Heroines Edition",
  "EB-02": "Anime 25th collection",
  "EB-01": "Memorial Collection",
  "OP-17": "The World's Strongest Warriors",
  "OP-16": "THE TIME OF BATTLE",
  "OP-15": "Adventure on KAMI’s Island",
  "OP-14": "The Azure Sea’s Seven",
  "OP-13": "Carrying on His Will",
  "OP-12": "Legacy of the Master",
  "OP-11": "A Fist of Divine Speed",
  "OP-10": "Royal Blood",
  "OP-09": "Emperors in the New World",
  "OP-08": "Two Legends",
  "OP-07": "500 Years in the Future",
  "OP-06": "Wings of Captain",
  "OP-05": "Awakening of the New Era",
  "OP-04": "Kingdoms of Intrigue",
  "OP-03": "Pillars of Strength",
  "OP-02": "Paramount War",
  "OP-01": "Romance Dawn",
  "ST-36": "Yellow Eustass\"Captain\"Kid",
  "ST-35": "Red/Black Sabo",
  "ST-34": "Purple Charlotte Katakuri",
  "ST-33": "Blue Kuzan",
  "ST-32": "Green Roronoa Zoro",
  "ST-31": "Red Monkey.D.Luffy",
  "ST-30": "Luffy & Ace",
  "ST-29": "EGGHEAD",
  "ST-28": "Green/Yellow Yamato",
  "ST-27": "Black Marshall.D.Teach",
  "ST-26": "Purple/Black Monkey.D.Luffy",
  "ST-25": "Blue Buggy",
  "ST-24": "Green Jewelry Bonney",
  "ST-23": "Red Shanks",
  "ST-22": "Ace & Newgate",
  "ST-21": "GEAR5",
  "ST-20": "Yellow Charlotte Katakuri",
  "ST-19": "Black Smoker",
  "ST-18": "Purple Monkey.D.Luffy",
  "ST-17": "Blue Donquixote Doflamingo",
  "ST-16": "Green Uta",
  "ST-15": "Red Edward.Newgate",
  "ST-14": "3D2Y",
  "ST-13": "The Three Brothers Bond",
  "ST-12": "Zoro & Sanji",
  "ST-11": "Side Uta",
  "ST-10": "The Three Captains",
  "ST-09": "Side Yamato",
  "ST-08": "Side Monkey.D.Luffy",
  "ST-07": "Big Mom Pirates",
  "ST-06": "The Navy",
  "ST-05": "ONE PIECE FILM edition",
  "ST-04": "Animal Kingdom Pirates",
  "ST-03": "The Seven Warlords of the Sea",
  "ST-02": "Worst Generation",
  "ST-01": "Straw Hat Crew",
};

export function releaseDisplayName(code: string, suppliedName?: string | null): string {
  return suppliedName?.trim() || (Object.hasOwn(OFFICIAL_RELEASE_NAMES, code)
    ? OFFICIAL_RELEASE_NAMES[code]
    : "Release name unavailable");
}
