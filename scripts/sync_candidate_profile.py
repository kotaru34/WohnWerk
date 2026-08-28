from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.jobs.candidate_fit import CandidatePreferenceSource
from app.jobs.candidate_profile_seed import (
    PROFILE_PREFERENCES,
    PROFILE_SEED_VERSION,
    PROFILE_SLUG,
)
from app.jobs.candidate_profile_store import (
    ConceptKey,
    concept_key,
    enabled_concepts,
    format_concept_keys,
    get_seed_profile,
    preference_rows,
    sync_seed_profile,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit/bootstrap the versioned candidate concept profile. Read-only by default; "
            "--apply creates/synchronizes seed-managed rows without overwriting manual rows."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist profile/seed preferences. Without this flag the command is read-only.",
    )
    return parser.parse_args()


def _audit(session: Session) -> None:
    concepts = enabled_concepts(session)
    missing_seed_concepts = [key for key in PROFILE_PREFERENCES if key not in concepts]
    profile = get_seed_profile(session)

    print(f"profile_seed_version={PROFILE_SEED_VERSION}")
    print(f"profile_slug={PROFILE_SLUG}")
    print(f"expected_seed_preferences={len(PROFILE_PREFERENCES)}")
    print(f"missing_seed_concepts={format_concept_keys(missing_seed_concepts)}")

    if profile is None:
        print("profile_exists=no")
        print("persisted_preferences=0")
        print("missing_seed_preferences=" + format_concept_keys(list(PROFILE_PREFERENCES)))
        print("seed_state_mismatches=-")
        print("manual_overrides=-")
        print("stale_seed_preferences=-")
        print("source_counts=-")
        print("state_counts=-")
        print("seed_version_counts=-")
        return

    rows = preference_rows(session, profile.id)
    by_key = {concept_key(concept): preference for preference, concept in rows}
    missing_seed_preferences = [key for key in PROFILE_PREFERENCES if key not in by_key]
    stale_seed_preferences: list[ConceptKey] = []
    seed_state_mismatches: list[ConceptKey] = []
    manual_overrides: list[ConceptKey] = []
    source_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    seed_version_counts: Counter[str] = Counter()

    for preference, concept in rows:
        key = concept_key(concept)
        source_counts[preference.source] += 1
        state_counts[preference.state] += 1
        if preference.source == CandidatePreferenceSource.SEED.value:
            seed_version_counts[preference.seed_version or "-"] += 1
            expected = PROFILE_PREFERENCES.get(key)
            if expected is None:
                stale_seed_preferences.append(key)
            elif preference.state != expected.value:
                seed_state_mismatches.append(key)
        elif preference.source == CandidatePreferenceSource.MANUAL.value:
            expected = PROFILE_PREFERENCES.get(key)
            if expected is not None and preference.state != expected.value:
                manual_overrides.append(key)

    print("profile_exists=yes")
    print(f"profile_id={profile.id}")
    print(f"profile_label_de={profile.label_de}")
    print(f"profile_enabled={'yes' if profile.enabled else 'no'}")
    print(f"persisted_preferences={len(rows)}")
    print(f"missing_seed_preferences={format_concept_keys(missing_seed_preferences)}")
    print(f"seed_state_mismatches={format_concept_keys(seed_state_mismatches)}")
    print(f"manual_overrides={format_concept_keys(manual_overrides)}")
    print(f"stale_seed_preferences={format_concept_keys(stale_seed_preferences)}")
    print(
        "source_counts="
        + (",".join(f"{key}:{source_counts[key]}" for key in sorted(source_counts)) or "-")
    )
    print(
        "state_counts="
        + (",".join(f"{key}:{state_counts[key]}" for key in sorted(state_counts)) or "-")
    )
    print(
        "seed_version_counts="
        + (
            ",".join(f"{key}:{seed_version_counts[key]}" for key in sorted(seed_version_counts))
            or "-"
        )
    )


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        if args.apply:
            try:
                sync_seed_profile(session)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            print("mode=apply")
            _audit(session)
        else:
            _audit(session)
            print("mode=read-only no database changes")


if __name__ == "__main__":
    main()
