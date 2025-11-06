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
# Bot setup
# ---------------------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Optional: use a guild for fast command registration; set GUILD_ID in env if desired
GUILD_ID = os.getenv("GUILD_ID")
GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None


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


def build_skillmod_embed(invoker_name: str, hero_counts: dict, res: dict):
    comp = res["components"]
    per_op_lines = []
    for (cat, op), tot in comp["per_op"].items():
        per_op_lines.append(f"{cat} op{op}: {tot*100:.1f}% (sum for that op)")

    # Friendly summary
    summary_lines = []
    if res["Damage%Increase"] > 0:
        summary_lines.append(
            f"💥 **You’ll deal about {res['Damage%Increase']:.0f}% more damage** than normal."
        )
    else:
        summary_lines.append("😐 **Your damage stays about the same.**")

    if res["DamageTaken%Change"] < 0:
        summary_lines.append(
            f"🛡️ **You’ll take about {abs(res['DamageTaken%Change']):.0f}% less damage** thanks to defense buffs."
        )
    elif res["DamageTaken%Change"] > 0:
        summary_lines.append(
            f"⚠️ **You’ll take about {res['DamageTaken%Change']:.0f}% more damage** than usual."
        )
    else:
        summary_lines.append("🛡️ **No change in damage taken.**")

    # Build embed
    embed = discord.Embed(title="SkillMod Calculator",
                          color=discord.Color.blurple())
    embed.set_footer(text=f"Requested by {invoker_name}")
    embed.add_field(name="Quick Summary",
                    value="\n".join(summary_lines),
                    inline=False)

    embed.add_field(name="SkillMod (multiplier)",
                    value=f"`{res['SkillMod']:.4f}×`",
                    inline=True)
    embed.add_field(name="Damage dealt",
                    value=f"`+{res['Damage%Increase']:.1f}%`",
                    inline=True)
    embed.add_field(
        name="Damage taken",
        value=
        f"`{res['FinalDamageTakenMultiplier']:.3f}×` ({res['DamageTaken%Change']:.1f}% change)",
        inline=True)

    embed.add_field(
        name="Breakdown (advanced users)",
        value=(f"- DamageUp factor: {comp['DamageUpFactor']:.3f}\n"
               f"- DefenseUp factor: {comp['DefenseUpFactor']:.3f}\n"
               f"- OppDefenseDown factor: {comp['OppDefenseDownFactor']:.3f}\n"
               f"- OppDamageDown factor: {comp['OppDamageDownFactor']:.3f}"),
        inline=False)

    # show per-op lines truncated if too long
    embed.add_field(name="Per-effect_op totals",
                    value="\n".join(per_op_lines[:10]) or "—",
                    inline=False)

    # footer note
    embed.add_field(
        name="Note",
        value=
        "Mixing different effect_op for the same effect multiplies benefits. See /help for examples.",
        inline=False)
    return embed


# ---------------------------
# Slash commands
# ---------------------------


# /help
@tree.command(name="help_skillmod",
              description="Show help for the SkillMod calculator")
async def help_skillmod(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**SkillMod Bot Help**\n\n"
        "Use `/skillmod` to calculate joiner effects. You can fill up to 6 hero slots.\n\n"
        "**Usage examples:**\n"
        "`/skillmod hero1: Chenko count1:4` — shows effect of 4 Chenkos\n"
        "`/skillmod hero1:Chenko count1:2 hero2:Amane count2:2` — compares mixed effect_ops\n\n"
        "Commands:\n"
        "• `/skillmod` — calculate with up to 6 hero slots\n"
        "• `/hero <name>` — show hero buff info\n"
        "• `/compare team_a:<string> team_b:<string>` — compare two team strings (e.g. `Chenko:4`)\n\n"
        "Tip: Use `/hero` or `/skillmod` hero autocomplete to avoid typos.\n"
        "Note: Mixing different effect_op for the same effect gives multiplicative stacking (stronger).",
        ephemeral=True)


# /hero <name>
@tree.command(name="hero", description="Get info about a specific joiner hero")
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
              description="Calculate SkillMod for up to 4 joiner heroes")
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
              description="Compare two teams. Use format: Chenko:4,Amane:2")
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
@tree.command(name="savepreset", description="Save a team preset under a name")
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
              description="Load a saved preset and calculate it")
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
@tree.command(name="listpresets", description="List your saved team presets")
async def listpresets(interaction: discord.Interaction):
    names = list_user_presets(str(interaction.user.id))
    if not names:
        await interaction.response.send_message(
            "You have no saved presets yet. Use /savepreset.", ephemeral=True)
        return
    await interaction.response.send_message("📚 Your presets:\n" +
                                            "\n".join(f"- {n}" for n in names),
                                            ephemeral=True)


# ---------------------------
# Register / sync on ready
# ---------------------------
# Confirm your environment is loading correctly

@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user} (id: {bot.user.id})")
    try:
        if GUILD:
            print(f"Attempting to sync commands to guild {GUILD_ID}...")
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
