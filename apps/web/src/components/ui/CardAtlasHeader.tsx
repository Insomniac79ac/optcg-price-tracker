"use client";

import { useRef, useState } from "react";

import styles from "@/app/cards/CardsAtlas.module.css";

/** Editorial identity and the catalogue's existing URL-backed search. */
export function CardAtlasHeader({
  query,
  onSearch,
  totalPrints,
}: {
  query: string;
  onSearch: (next: string) => void;
  totalPrints: number | null;
}) {
  return (
    <section className={styles.identity} aria-labelledby="card-atlas-title">
      <p className={styles.kicker}>Japanese One Piece singles</p>
      <div className={styles.identityBody}>
        <div>
          <h1 id="card-atlas-title" className={styles.heading}>THE CARD ATLAS</h1>
          <p className={styles.description}>
            <strong>Base, parallel and alt-art printings remain distinct entries.</strong>
          </p>
        </div>

        <div className={styles.searchArea}>
          {query ? (
            <p className={styles.queryContext}>
              <strong>&ldquo;{query}&rdquo;</strong> in the Atlas
              {totalPrints !== null && (
                <span className={styles.resultCount}>
                  {totalPrints.toLocaleString()} {totalPrints === 1 ? "printing" : "printings"}
                </span>
              )}
            </p>
          ) : null}
          <CardAtlasSearch query={query} onSearch={onSearch} />
        </div>
      </div>
    </section>
  );
}

function CardAtlasSearch({ query, onSearch }: { query: string; onSearch: (next: string) => void }) {
  const [value, setValue] = useState(query);
  const [committed, setCommitted] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);

  if (query !== committed) {
    setCommitted(query);
    setValue(query);
  }

  function commitIfCleared(next: string) {
    if (query && next.trim() === "") onSearch("");
  }

  function clear() {
    setValue("");
    commitIfCleared("");
    inputRef.current?.focus();
  }

  return (
    <form
      role="search"
      className={styles.searchForm}
      onSubmit={(event) => {
        event.preventDefault();
        onSearch(value.trim());
      }}
    >
      <div className={styles.searchField}>
        <input
          ref={inputRef}
          type="search"
          name="q"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            commitIfCleared(event.target.value);
          }}
          placeholder="Search by card code or name…"
          aria-label="Search prints by card code, English name, or Japanese name"
          className={styles.searchInput}
        />
        {value !== "" && (
          <button type="button" onClick={clear} aria-label="Clear search" className={styles.clearSearch}>
            ×
          </button>
        )}
      </div>
      <button type="submit" className={styles.searchButton}>Search</button>
    </form>
  );
}
