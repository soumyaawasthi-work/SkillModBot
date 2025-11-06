# bot.py
# Full-featured SkillMod bot with slash commands, autocomplete, embeds.
# Expects environment variable DISCORD_BOT_TOKEN to be set.
# Optional: set GUILD_ID (string) to a guild id to register commands instantly there.

import os
import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict
from math import prod
from typing import Optional
import asyncio
import json

# ---------------------------
# Hero data (confirmed values)
# ---------------------------
# Format: "HeroName": [ (category, effect_op, decimal_value), ... ]
HERO_DATA = {
    "Chenko": [("DamageUp", 101, 0.25)],
    "Amadeus": [("DamageUp", 101, 0.25)],
    "Yeonwoo": [("DamageUp", 101, 0.25)],
    "Amane": [("DamageUp", 102, 0.25)],
    "Howard": [("DefenseUp", 111, 0.20)],
    "Quinn": [("DefenseUp", 111, 0.20)],
    "Gordon": [("DefenseUp", 113, 0.25)],
    "Fahd": [("OppDamageDown", 201, 0.20)],
    "Saul": [("DefenseUp", 112, 0.10), ("DefenseUp", 113, 0.15)],
    "Hilde": [("DefenseUp", 112, 0.10), ("DamageUp", 102, 0.15)],
    "Eric": [("OppDamageDown", 202, 0.20)],
    "Margot": [("DamageUp", 102, 0.25)],
}

# list for autocomplete
HERO_NAMES = sorted(HERO_DATA.keys(), key=lambda s: s.lower())

# ---------------------------
# Preset management
# ---------------------------

PRESET_FILE = "presets.json"


def load_all_presets():
    if not os.path.exists(PRESET_FILE):
        return {}
    try:
        with open(PRESET_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_all_presets(data):
    with open(PRESET_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_user_preset(user_id: str, name: str, team_string: str):
    presets = load_all_presets()
    user_presets = presets.get(user_id, {})
    user_presets[name] = team_string
    presets[user_id] = user_presets
    save_all_presets(presets)


def load_user_preset(user_id: str, name: str):
    presets = load_all_presets()
    return presets.get(user_id, {}).get(name)


def list_user_presets(user_id: str):
    presets = load_all_presets()
    return list(presets.get(user_id, {}).keys())


# ---------------------------
# Math functions (per article)
# ---------------------------


def compute_factors_from_hero_counts(hero_counts):
    """
    hero_counts: dict e.g. {"Chenko": 4, "Amane": 2}
    Returns per-op sums and final multiplicative factors per category.
    """
    per_op = defaultdict(float)  # key: (category, op) -> sum of decimals

    for hero, count in hero_counts.items():
        if hero not in HERO_DATA:
            raise KeyError(hero)
        for (cat, op, pct) in HERO_DATA[hero]:
            per_op[(cat, op)] += pct * count

    def category_factor(cat_name):
        factors = []
        for (cat, op), total_pct in per_op.items():
            if cat == cat_name:
                factors.append(1.0 + total_pct)  # (1 + sum_pct_for_this_op)
        return prod(factors) if factors else 1.0

    dmg_factor = category_factor("DamageUp")
    def_factor = category_factor("DefenseUp")
    opp_def_factor = category_factor("OppDefenseDown")
    opp_dmg_factor = category_factor("OppDamageDown")

    return {
        "per_op": per_op,
        "DamageUpFactor": dmg_factor,
        "DefenseUpFactor": def_factor,
        "OppDefenseDownFactor": opp_def_factor,
        "OppDamageDownFactor": opp_dmg_factor
    }


def calculate_skillmod(hero_counts):
    """
    Returns a dict with SkillMod and user-friendly stats.
    """
    groups = compute_factors_from_hero_counts(hero_counts)
    dmg_f = groups["DamageUpFactor"]
    def_f = groups["DefenseUpFactor"]
    opp_def_f = groups["OppDefenseDownFactor"]
    opp_dmg_f = groups["OppDamageDownFactor"]

    # SkillMod per article: (DamageUp * OppDefenseDown) / (OppDamageDown * DefenseUp)
    # note: we already computed factors as (1 + sums) per-op multiplied across ops
    # so use them directly:
    # guard against zero in denominator
    denom = opp_dmg_f * def_f if (opp_dmg_f * def_f) != 0 else 1.0
    skillmod = (dmg_f * opp_def_f) / denom

    damage_percent_increase = (skillmod - 1.0) * 100.0

    # For damage taken, model enemy outgoing reduction from OppDamageDown as reciprocal of opp_dmg_f
    # (so higher OppDamageDown reduces enemy damage).
    enemy_reduction_factor = 1.0 / opp_dmg_f if opp_dmg_f != 0 else 1.0
    final_damage_taken_multiplier = (1.0 / def_f) * enemy_reduction_factor
    damage_taken_percent_change = (final_damage_taken_multiplier -
                                   1.0) * 100.0  # negative = less damage taken

    return {
        "SkillMod": skillmod,
        "Damage%Increase": damage_percent_increase,
        "FinalDamageTakenMultiplier": final_damage_taken_multiplier,
        "DamageTaken%Change": damage_taken_percent_change,
        "components": groups
    }


# ---------------------------
# Utilities: parsing hero input
# ---------------------------


def parse_pairs_input(args_dict):
    """
    Accepts a mapping of hero_name->count from slash command fields.
    Normalizes names (case-insensitive) to canonical keys.
    """
    normalized = {}
    for raw_name, cnt in args_dict.items():
        if not raw_name:
            continue
        # match case-insensitive
        matched = None
        for h in HERO_DATA:
            if h.lower() == raw_name.lower():
                matched = h
                break
        if not matched:
            raise KeyError(raw_name)
        if cnt is None or cnt <= 0:
            continue
        normalized[matched] = normalized.get(matched, 0) + int(cnt)
    return normalized


def parse_compact_string(s: str):
    """
    Accept "Chenko:4,Amane:2" or "Chenko 4 Amane 2" style, returns normalized dict.
    """
    if not s:
        return {}
    parts = []
    if "," in s:
        raw_items = [p.strip() for p in s.split(",") if p.strip()]
        for it in raw_items:
            parts.append(it)
    else:
        parts = s.split()

    hero_counts = {}
    for it in parts:
        if ":" in it:
            name, cnt = it.split(":", 1)
            name = name.strip()
            cnt = int(cnt.strip())
        else:
            # fallback: if single token like "Chenko4" or "Chenko 4"
            # not robust — user should use "Name:count" or pairs
            # try to split letters vs digits
            # but for clarity, raise if format unknown
            raise ValueError(
                "Use format: Chenko:4,Amane:2 or pairs. Example: Chenko 4 Amane 2"
            )
        # normalize
        matched = None
        for h in HERO_DATA:
            if h.lower() == name.lower():
                matched = h
                break
        if not matched:
            raise KeyError(name)
        hero_counts[matched] = hero_counts.get(matched, 0) + cnt
    return hero_counts


# ---------------------------
# Recommendation Management
# ---------------------------


RECOMMEND_CACHE_FILE = "recommend_cache.json"

def load_recommend_cache():
    """Load cached global best formations."""
    if not os.path.exists(RECOMMEND_CACHE_FILE):
        return {}
    with open(RECOMMEND_CACHE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_recommend_cache(data):
    """Save cached results."""
    with open(RECOMMEND_CACHE_FILE, "w") as f:
        json.dump(data, f)


def parse_roster_string(roster_str):
    """Parse 'Chenko:3,Amane:2' into dict."""
    heroes = {}
    parts = roster_str.split(",")
    for p in parts:
        if not p.strip():
            continue
        try:
            name, count = p.split(":")
            heroes[name.strip()] = int(count.strip())
        except ValueError:
            raise ValueError(f"Invalid format near '{p}'")
    return heroes


def generate_combinations(roster_counts, max_size=4):
    """Generate all combinations within hero limits."""
    names = list(roster_counts.keys())
    combos = set()

    def helper(prefix, start):
        if len(prefix) == max_size:
            combos.add(tuple(sorted(prefix)))
            return
        for i in range(start, len(names)):
            hero = names[i]
            if prefix.count(hero) < roster_counts[hero]:
                helper(prefix + [hero], i)

    helper([], 0)
    return combos


def get_best_formations(roster_counts=None):
    """Compute best 2 formations for attack and garrison."""
    all_heroes = roster_counts or {name: 4 for name in HERO_DATA.keys()}

    combos = generate_combinations(all_heroes, max_size=4)
    results = []

    for combo in combos:
        hero_counts = {h: combo.count(h) for h in set(combo)}
        res = calculate_skillmod(hero_counts)
        results.append({
            "heroes": hero_counts,
            "skillmod": res["skillmod"],
            "damage_pct": res["damage_dealt_change"],
            "taken_pct": res["damage_taken_change"],
        })

    # Attack ranking → highest damage%
    best_attack = sorted(results, key=lambda x: x["damage_pct"], reverse=True)[:2]
    # Garrison ranking → lowest damage taken%
    best_garrison = sorted(results, key=lambda x: x["taken_pct"])[:2]

    return best_attack, best_garrison


def format_formations(sets):
    lines = []
    for i, s in enumerate(sets, 1):
        heroes = ", ".join(f"{h}×{c}" for h, c in s["heroes"].items())
        dmg = s["damage_pct"]
        taken = s["taken_pct"]
        sm = s["skillmod"]
        lines.append(
            f"**{i}.** {heroes} — SkillMod `{sm:.3f}×`\n💥 Damage: `{dmg:+.1f}%`, 🛡️ Damage Taken: `{taken:+.1f}%`"
        )
    return "\n\n".join(lines) if lines else "No valid formations found."


# ---------------------------
# Bot setup
# ---------------------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Optional: use a guild for fast command registration; set GUILD_ID in env if desired
GUILD_ID = os.getenv("GUILD_ID")
GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None
guild_param = [GUILD] if GUILD else None

# ---------------------------
# Autocomplete helper
# ---------------------------
async def hero_autocomplete(interaction: discord.Interaction, current: str):
    current = current or ""
    choices = [
        app_commands.Choice(name=h, value=h) for h in HERO_NAMES
        if current.lower() in h.lower()
    ]
    return choices[:25]


# ---------------------------
# Embeds & reply formatting
# ---------------------------


def build_skillmod_embed(username, hero_counts, result):
    # Determine factors
    damage_factor = result["damage_factor"]
    defense_factor = result["defense_factor"]

    damage_change = (damage_factor - 1) * 100
    defense_change = (1 - defense_factor) * 100

    # ---------------------------
    # Quick Summary
    # ---------------------------
    if abs(damage_change) < 0.01:
        damage_line = "💥 You deal the same damage as a neutral (no-joiner) setup."
    else:
        damage_line = f"💥 You deal {damage_change:+.1f}% damage compared to a neutral setup."

    if abs(defense_change) < 0.01:
        defense_line = "🛡️ You take the same damage as a neutral (no-joiner) setup."
    else:
        defense_line = f"🛡️ You take {(-defense_change):+.1f}% damage compared to a neutral setup."

    summary = f"**Quick Summary**\n{damage_line}\n{defense_line}\n\n"

    # ---------------------------
    # SkillMod Multiplier Section
    # ---------------------------
    skillmod_section = (
        f"**SkillMod (combined multiplier)**\n"
        f"Damage dealt: **{damage_factor:.4f}×**\n"
        f"Damage taken: **{defense_factor:.4f}×**\n\n"
    )

    # ---------------------------
    # Detailed Breakdown Section
    # ---------------------------
    breakdown = (
        "**Breakdown (for advanced users)**\n"
        f"DamageUp factor: {result['damageup_factor']:.3f}\n"
        f"DefenseUp factor: {result['defenseup_factor']:.3f}\n"
        f"OppDefenseDown factor: {result['oppdefensedown_factor']:.3f}\n"
        f"OppDamageDown factor: {result['oppdamagedown_factor']:.3f}\n\n"
    )

    # ---------------------------
    # Per-effect_op Details
    # ---------------------------
    per_op = "**Per-effect_op totals**\n"
    for eff, ops in result["effect_op_totals"].items():
        for op, val in ops.items():
            per_op += f"{eff} op{op}: {val:.1f}%\n"
    per_op += "\n"

    # ---------------------------
    # Clarification Note
    # ---------------------------
    note = (
        "_'Neutral' means a base setup with no joiner heroes on either side._\n"
        "_Positive % = you deal or take more damage than neutral; "
        "negative % = you deal or take less damage than neutral._"
    )

    # ---------------------------
    # Determine Embed Color (contextual)
    # ---------------------------
    if damage_factor > 1.0 and defense_factor < 1.0:
        color = discord.Color.gold()     # Strong offense & defense
    elif damage_factor > 1.0:
        color = discord.Color.red()      # Offensive boost
    elif defense_factor < 1.0:
        color = discord.Color.blue()     # Defensive boost
    else:
        color = discord.Color.dark_gray()  # Neutral / no major change

    # ---------------------------
    # Build Embed
    # ---------------------------
    embed = discord.Embed(
        title=f"SkillMod Analysis for {username}",
        description=summary + skillmod_section + breakdown + per_op + note,
        color=color
    )

    # Add hero list field
    hero_list = "\n".join(f"{h}: {c}" for h, c in hero_counts.items())
    embed.add_field(name="Team Composition", value=hero_list or "None", inline=False)

    return embed


# ---------------------------
# Slash commands
# ---------------------------


# /help
@tree.command(name="help_skillmod",
              description="Show help for the SkillMod calculator", guilds=guild_param)
async def help_skillmod(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**SkillMod Bot Help**\n\n"
"Use `/skillmod` to calculate how your joiner lineup affects battle performance.\n"
"You can test different hero combinations, save your favorite teams, and even get AI-based formation recommendations.\n\n"

"**🧮 Core Commands**\n"
"• `/skillmod` — Calculate your SkillMod multiplier using up to 4 heroes.\n"
"   👉 Example: `/skillmod hero1:Chenko count1:2 hero2:Amane count2:2`\n"
"• `/hero <name>` — Show hero buff type, effect_op, and contribution.\n"
"   👉 Example: `/hero Hilde`\n"
"• `/compare team_a:<string> team_b:<string>` — Compare two team setups.\n"
"   👉 Example: `/compare team_a:Chenko:4 team_b:Amane:2,Chenko:2`\n\n"

"**💾 Preset Commands**\n"
"• `/savepreset name:<name> heroes:<list>` — Save a team setup for later use.\n"
"   👉 Example: `/savepreset name:AttackA heroes:Chenko:2,Amane:2`\n"
"• `/loadpreset name:<name>` — Load and calculate a saved team.\n"
"   👉 Example: `/loadpreset name:AttackA`\n"
"• `/listpresets` — View all your saved team presets.\n\n"

"**🤖 Recommendation Command**\n"
"• `/recommend` — Suggests top 2 team formations for both Attack and Garrison.\n"
"   👉 `/recommend` — shows global best 4-hero setups.\n"
"   👉 `/recommend heroes:Chenko:3,Amane:2,Hilde:1` — suggests best teams using only heroes you own.\n\n"

"**💡 Tips**\n"
"• Mixing heroes with the same *effect* but **different effect_op** (e.g., Chenko & Amane) gives multiplicative stacking and higher SkillMod.\n"
"• You can use `/hero` autocomplete to avoid typos.\n"
"• Presets are saved per user, so each player can manage their own setups.\n"
"• `/recommend` uses real SkillMod calculations — no assumptions or flat bonuses.\n\n"

"**Summary:**\n"
"Start with `/skillmod` to test your joiners → save good builds with `/savepreset` → and use `/recommend` to discover the best possible formations.",

        ephemeral=True)


# /hero <name>
@tree.command(name="hero", description="Get info about a specific joiner hero", guilds=guild_param)
@app_commands.describe(name="Hero name")
@app_commands.autocomplete(name=hero_autocomplete)
async def slash_hero(interaction: discord.Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    # normalize
    matched = None
    for h in HERO_DATA:
        if h.lower() == name.lower():
            matched = h
            break
    if not matched:
        await interaction.followup.send(
            f"Unknown hero `{name}`. Type `/help_skillmod` or check `/skillmod` autocomplete.",
            ephemeral=True)
        return

    effects = HERO_DATA[matched]
    lines = []
    for cat, op, pct in effects:
        lines.append(f"- **{cat}** (op{op}): {pct*100:.0f}%")
    text = f"**{matched}**\n" + "\n".join(lines)
    await interaction.followup.send(text, ephemeral=True)


# /skillmod with up to 4 hero slots (each optional). Autocomplete for each hero
@tree.command(name="skillmod",
              description="Calculate SkillMod for up to 4 joiner heroes", guilds=guild_param)
@app_commands.describe(
    hero1="Hero 1",
    count1="Count for hero 1",
    hero2="Hero 2",
    count2="Count for hero 2",
    hero3="Hero 3",
    count3="Count for hero 3",
    hero4="Hero 4",
    count4="Count for hero 4",
)
@app_commands.autocomplete(hero1=hero_autocomplete,
                           hero2=hero_autocomplete,
                           hero3=hero_autocomplete,
                           hero4=hero_autocomplete)
async def slash_skillmod(
    interaction: discord.Interaction,
    hero1: Optional[str] = None,
    count1: int = 1,
    hero2: Optional[str] = None,
    count2: int = 1,
    hero3: Optional[str] = None,
    count3: int = 1,
    hero4: Optional[str] = None,
    count4: int = 1,
):
    await interaction.response.defer()
    try:
        pairs = {
            hero1: count1,
            hero2: count2,
            hero3: count3,
            hero4: count4,
        }
        normalized = parse_pairs_input(pairs)
    except KeyError as e:
        await interaction.followup.send(
            f"Unknown hero `{e.args[0]}`. Use autocomplete or /help_skillmod.",
            ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(
            "Parse error. Use /help_skillmod for usage examples.",
            ephemeral=True)
        return

    if not normalized:
        await interaction.followup.send(
            "No heroes provided. Use /skillmod and pick at least one hero.",
            ephemeral=True)
        return

    res = calculate_skillmod(normalized)
    embed = build_skillmod_embed(interaction.user.display_name, normalized,
                                 res)
    await interaction.followup.send(embed=embed)


# /compare team_a team_b
@tree.command(name="compare",
              description="Compare two teams. Use format: Chenko:4,Amane:2", guilds=guild_param)
@app_commands.describe(team_a="Team A (e.g. Chenko:4,Amane:2)",
                       team_b="Team B (e.g. Chenko:2,Amane:2)")
async def slash_compare(interaction: discord.Interaction, team_a: str,
                        team_b: str):
    await interaction.response.defer()
    try:
        a = parse_compact_string(team_a)
        b = parse_compact_string(team_b)
    except KeyError as e:
        await interaction.followup.send(
            f"Unknown hero `{e.args[0]}` in input. Use /help_skillmod.",
            ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(
            "Parse error. Use format: Chenko:4,Amane:2", ephemeral=True)
        return

    ra = calculate_skillmod(a)
    rb = calculate_skillmod(b)
    va = ra["SkillMod"]
    vb = rb["SkillMod"]
    delta = (vb - va) / va * 100 if va != 0 else 0.0
    winner = "Team B" if vb > va else ("Team A" if va > vb else "Tie")

    embed = discord.Embed(title="Team Comparison", color=discord.Color.teal())
    embed.add_field(
        name="Team A",
        value=
        f"`{team_a}`\nSkillMod: `{va:.4f}`\nDamage: `+{ra['Damage%Increase']:.1f}%`",
        inline=True)
    embed.add_field(
        name="Team B",
        value=
        f"`{team_b}`\nSkillMod: `{vb:.4f}`\nDamage: `+{rb['Damage%Increase']:.1f}%`",
        inline=True)
    embed.add_field(
        name="Result",
        value=
        f"{winner} wins (Team B is {delta:.1f}% {'higher' if delta>0 else 'lower'} than Team A)",
        inline=False)
    await interaction.followup.send(embed=embed)


# /savepreset name: <username> heroes: <hero name>:<hero count>, <hero name>: <hero count>
@tree.command(name="savepreset", description="Save a team preset under a name", guilds=guild_param)
@app_commands.describe(name="Preset name",
                       heroes="Heroes list, e.g. Chenko:4,Amane:2")
async def savepreset(interaction: discord.Interaction, name: str, heroes: str):
    try:
        _ = parse_compact_string(heroes)  # validate
    except Exception as e:
        await interaction.response.send_message(
            "Invalid format. Use `Hero:count,Hero:count`.", ephemeral=True)
        return
    save_user_preset(str(interaction.user.id), name, heroes)
    await interaction.response.send_message(f"✅ Preset `{name}` saved!",
                                            ephemeral=True)


# /loadpreset name: <username>
@tree.command(name="loadpreset",
              description="Load a saved preset and calculate it", guilds=guild_param)
@app_commands.describe(name="Preset name")
async def loadpreset(interaction: discord.Interaction, name: str):
    saved = load_user_preset(str(interaction.user.id), name)
    if not saved:
        avail = list_user_presets(str(interaction.user.id))
        msg = "You have no preset by that name."
        if avail:
            msg += f" Your presets: {', '.join(avail)}"
        await interaction.response.send_message(msg, ephemeral=True)
        return
    try:
        hero_counts = parse_compact_string(saved)
        res = calculate_skillmod(hero_counts)
        embed = build_skillmod_embed(interaction.user.display_name,
                                     hero_counts, res)
        embed.title = f"Preset: {name}"
        await interaction.response.send_message(embed=embed)
    except Exception:
        await interaction.response.send_message("Error reading preset.",
                                                ephemeral=True)


# /listpresets
@tree.command(name="listpresets", description="List your saved team presets", guilds=guild_param)
async def listpresets(interaction: discord.Interaction):
    names = list_user_presets(str(interaction.user.id))
    if not names:
        await interaction.response.send_message(
            "You have no saved presets yet. Use /savepreset.", ephemeral=True)
        return
    await interaction.response.send_message("📚 Your presets:\n" +
                                            "\n".join(f"- {n}" for n in names),
                                            ephemeral=True)


# /recommend
@tree.command(
    name="recommend",
    description="Suggests top 2 team formations for attack and garrison. Use heroes:Chenko:3,Amane:2 to limit to your roster.", guilds=guild_param
)
@app_commands.describe(
    heroes="(Optional) List your available heroes, e.g., Chenko:3,Amane:2"
)
async def recommend(interaction: discord.Interaction, heroes: str = None):
    await interaction.response.defer(thinking=True)

    cache = load_recommend_cache()
    now = datetime.utcnow()

    if heroes:
        try:
            roster_counts = parse_roster_string(heroes)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        best_attack, best_garrison = get_best_formations(roster_counts)
        roster_note = f"*(Based on your roster: {heroes})*"
    else:
        if "timestamp" in cache:
            ts = datetime.fromisoformat(cache["timestamp"])
            if now - ts < timedelta(days=1):
                best_attack = cache["best_attack"]
                best_garrison = cache["best_garrison"]
            else:
                best_attack, best_garrison = get_best_formations()
                cache = {
                    "timestamp": now.isoformat(),
                    "best_attack": best_attack,
                    "best_garrison": best_garrison,
                }
                save_recommend_cache(cache)
        else:
            best_attack, best_garrison = get_best_formations()
            cache = {
                "timestamp": now.isoformat(),
                "best_attack": best_attack,
                "best_garrison": best_garrison,
            }
            save_recommend_cache(cache)
        roster_note = "*(Based on all heroes — cached global best)*"

    embed = discord.Embed(
        title="🔥 Recommended Formations",
        description=roster_note,
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="💥 Attack Focus (Damage Output)",
        value=format_formations(best_attack),
        inline=False,
    )
    embed.add_field(
        name="🛡️ Garrison Focus (Damage Reduction)",
        value=format_formations(best_garrison),
        inline=False,
    )

    await interaction.followup.send(embed=embed)
    
# --------------------------
# Register / sync on ready
# --------------------------


@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user} (id: {bot.user.id})")
    print(f"Loaded slash commands: {[cmd.name for cmd in tree.get_commands()]}")
    try:
        if GUILD:
            print(f"Attempting to sync commands to guild {GUILD_ID}...")
            # tree.clear_commands(guild=GUILD)
            synced = await tree.sync(guild=GUILD)
            print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")
        else:
            print("⚠️ GUILD not defined. Syncing globally (may take up to 1 hour)...")
            synced = await tree.sync()
            print(f"✅ Synced {len(synced)} global commands")
    except Exception as e:
        print("❌ Failed to sync slash commands:", e)

# ---------------------------
# Run
# ---------------------------

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: set DISCORD_BOT_TOKEN in environment")
        raise SystemExit(1)
    bot.run(TOKEN)
