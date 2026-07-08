from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))


DEFAULT_OUTPUT = "Data/RumorSpread/social_seed.pheme.generated.json"


def _read_json(path: Path) -> dict[str, Any]:
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except UnicodeDecodeError:
		data = json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(data, dict):
		raise ValueError(f"expected JSON object: {path}")
	return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_id(value: Any, prefix: str) -> str:
	raw = str(value or "").strip()
	if not raw:
		raw = "unknown"
	cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", raw).strip("_")
	return f"{prefix}_{cleaned or 'unknown'}"


def _clean_tag(value: Any) -> str:
	raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
	return re.sub(r"[^0-9a-z_]+", "", raw)


def _tweet_text(tweet: dict[str, Any]) -> str:
	for key in ("full_text", "text"):
		value = str(tweet.get(key, "") or "").strip()
		if value:
			return value
	return ""


def _user_payload(tweet: dict[str, Any]) -> dict[str, Any]:
	user = tweet.get("user", {})
	if not isinstance(user, dict):
		user = {}
	user_id = user.get("id_str") or user.get("id") or tweet.get("user_id") or tweet.get("user_id_str")
	account_id = _clean_id(user_id, "pheme_acc")
	display_name = str(user.get("name") or user.get("screen_name") or account_id).strip()
	if not display_name:
		display_name = account_id
	bio = str(user.get("description", "") or "").strip()
	return {
		"account_id": account_id,
		"display_name": display_name,
		"bio": bio,
		"interests": {"pheme": 1.0},
	}


def _external_source_account(label: str) -> dict[str, Any]:
	if label == "rumor":
		return {
			"account_id": "external_pheme_rumor_source",
			"display_name": "External PHEME Rumor Source",
			"bio": "Imported source account for PHEME rumor seed posts. It is not a KERN agent.",
			"interests": {"pheme": 1.0, "rumor": 1.0},
		}
	return {
		"account_id": "external_pheme_background_source",
		"display_name": "External PHEME Background Source",
		"bio": "Imported source account for PHEME background posts. It is not a KERN agent.",
		"interests": {"pheme": 1.0, "background": 1.0, "non_rumor": 1.0},
	}


def _parse_created_at(value: Any) -> datetime | None:
	text = str(value or "").strip()
	if not text:
		return None
	for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
		try:
			return datetime.strptime(text, fmt)
		except ValueError:
			pass
	if text.endswith("Z"):
		try:
			return datetime.fromisoformat(text[:-1] + "+00:00")
		except ValueError:
			return None
	try:
		parsed = datetime.fromisoformat(text)
	except ValueError:
		return None
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=timezone.utc)
	return parsed


def _label_from_path(path: Path) -> str | None:
	parts = {_clean_tag(part) for part in path.parts}
	if "rumours" in parts or "rumors" in parts:
		return "rumor"
	if "non_rumours" in parts or "non_rumors" in parts or "nonrumours" in parts or "nonrumors" in parts:
		return "non_rumor"
	return None


def _event_from_path(source_file: Path) -> str:
	parts = list(source_file.parts)
	for idx, part in enumerate(parts):
		tag = _clean_tag(part)
		if tag in {"rumours", "rumors", "non_rumours", "non_rumors", "nonrumours", "nonrumors"} and idx > 0:
			return _clean_tag(parts[idx - 1]) or "pheme"
	return "pheme"


def _source_tweet_files(pheme_root: Path) -> list[Path]:
	return sorted(pheme_root.glob("**/source-tweets/*.json"))


def _build_source_rows(pheme_root: Path) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for source_file in _source_tweet_files(pheme_root):
		label = _label_from_path(source_file)
		if not label:
			continue
		tweet = _read_json(source_file)
		text = _tweet_text(tweet)
		if not text:
			continue
		tweet_id = str(tweet.get("id_str") or tweet.get("id") or source_file.stem)
		user = _user_payload(tweet)
		rows.append(
			{
				"source_file": str(source_file),
				"tweet_id": tweet_id,
				"text": text,
				"created_at": _parse_created_at(tweet.get("created_at")),
				"event": _event_from_path(source_file),
				"label": label,
				"account": user,
			}
		)
	return rows


def _sample_rows(rows: list[dict[str, Any]], *, rumor_count: int, noise_count: int, seed: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	rng = random.Random(seed)
	rumors = [row for row in rows if row["label"] == "rumor"]
	noise = [row for row in rows if row["label"] != "rumor"]
	rng.shuffle(rumors)
	rng.shuffle(noise)
	selected_rumors = rumors[: max(0, rumor_count)]
	if len(noise) < noise_count:
		extras = [row for row in rows if row not in selected_rumors]
		rng.shuffle(extras)
		selected_noise = extras[: max(0, noise_count)]
	else:
		selected_noise = noise[: max(0, noise_count)]
	return selected_rumors, selected_noise


def _minutes_to_ticks(rows: list[dict[str, Any]], tick_minutes: int) -> dict[str, int]:
	timed = [row["created_at"] for row in rows if isinstance(row.get("created_at"), datetime)]
	base = min(timed) if timed else None
	out: dict[str, int] = {}
	for idx, row in enumerate(rows):
		if base is not None and isinstance(row.get("created_at"), datetime):
			delta = row["created_at"] - base
			tick = int(delta.total_seconds() // max(60, tick_minutes * 60))
		else:
			tick = idx
		out[row["tweet_id"]] = max(0, tick)
	return out


def build_seed(
	pheme_root: Path,
	*,
	rumor_count: int,
	noise_count: int,
	seed: str,
	tick_minutes: int,
	max_text_chars: int,
	source_accounts: str = "external",
) -> dict[str, Any]:
	rows = _build_source_rows(pheme_root)
	selected_rumors, selected_noise = _sample_rows(rows, rumor_count=rumor_count, noise_count=noise_count, seed=seed)
	selected = selected_rumors + selected_noise
	ticks = _minutes_to_ticks(selected, tick_minutes=tick_minutes)

	accounts_by_id: dict[str, dict[str, Any]] = {}
	posts: list[dict[str, Any]] = []
	for idx, row in enumerate(selected, start=1):
		if source_accounts == "tweet_authors":
			account = dict(row["account"])
			account["interests"] = {
				"pheme": 1.0,
				str(row["event"]): 1.0,
				str(row["label"]): 1.0,
			}
		else:
			account = _external_source_account(str(row["label"]))
		accounts_by_id[account["account_id"]] = account
		tags = ["pheme", str(row["event"]), str(row["label"]), "source_post"]
		if row["label"] != "rumor":
			tags.append("background")
		text = str(row["text"])
		if max_text_chars > 0 and len(text) > max_text_chars:
			text = text[: max_text_chars - 3].rstrip() + "..."
		posts.append(
			{
				"account_id": account["account_id"],
				"post_id": _clean_id(row["tweet_id"], "pheme_post"),
				"text": text,
				"tags": tags,
				"tick": int(ticks.get(row["tweet_id"], idx - 1)),
			}
		)

	return {
		"metadata": {
			"source": "PHEME",
			"source_root": str(pheme_root),
			"seed": seed,
			"rumor_count": len(selected_rumors),
			"noise_count": len(selected_noise),
			"tick_minutes": tick_minutes,
			"available_source_tweets": len(rows),
			"source_accounts": source_accounts,
			"conversion_note": "PHEME source tweets are converted into KERN social seed posts; agent profiles and follow graph are supplied separately. Default source accounts are external data-source accounts, not KERN agents.",
		},
		"accounts": sorted(accounts_by_id.values(), key=lambda x: x["account_id"]),
		"posts": sorted(posts, key=lambda x: (int(x.get("tick", 0)), str(x.get("post_id", "")))),
		"follows": [],
	}


def main() -> None:
	parser = argparse.ArgumentParser(description="Convert local PHEME source tweets into a KERN social_seed JSON file.")
	parser.add_argument("pheme_root", help="Path to an extracted PHEME dataset root.")
	parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output social seed JSON path.")
	parser.add_argument("--rumor-count", type=int, default=1, help="Number of rumor source tweets to include.")
	parser.add_argument("--noise-count", type=int, default=100, help="Number of non-rumor/background source tweets to include.")
	parser.add_argument("--seed", default="kern-pheme-seed-v1", help="Deterministic sampling seed.")
	parser.add_argument("--tick-minutes", type=int, default=3, help="Minutes represented by one KERN tick for source tweet timing.")
	parser.add_argument("--max-text-chars", type=int, default=280, help="Trim post text to this many characters; <=0 keeps full text.")
	parser.add_argument(
		"--source-accounts",
		choices=["external", "tweet_authors"],
		default="external",
		help="Use external data-source accounts by default, or preserve PHEME tweet authors as platform accounts.",
	)
	args = parser.parse_args()

	pheme_root = Path(args.pheme_root)
	if not pheme_root.is_absolute():
		pheme_root = ROOT / pheme_root
	if not pheme_root.exists():
		raise SystemExit(f"PHEME root does not exist: {pheme_root}")
	out_path = Path(args.output)
	if not out_path.is_absolute():
		out_path = ROOT / out_path

	seed_data = build_seed(
		pheme_root,
		rumor_count=max(0, int(args.rumor_count)),
		noise_count=max(0, int(args.noise_count)),
		seed=str(args.seed),
		tick_minutes=max(1, int(args.tick_minutes)),
		max_text_chars=int(args.max_text_chars),
		source_accounts=str(args.source_accounts),
	)
	_write_json(out_path, seed_data)
	print(
		f"wrote {len(seed_data['posts'])} PHEME posts and {len(seed_data['accounts'])} accounts to {out_path}"
	)


if __name__ == "__main__":
	main()
