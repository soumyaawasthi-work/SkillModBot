import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

# ---- HERO MULTIPLIERS + VALUES YOU PROVIDED ----
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

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def calculate_skillmod(hero_input):
    total_damage = 0
    total_defense = 0
    total_oppdmg = 0

    for hero, count in hero_input.items():
        if hero not in HERO_DATA:
            return None, None, None, hero  # error

        for effect, _, value in HERO_DATA[hero]:
            buff_total = value * count

            if effect == "DamageUp":
                total_damage += buff_total
            elif effect == "DefenseUp":
                total_defense += buff_total
            elif effect == "OppDamageDown":
                total_oppdmg += buff_total

    skillmod = (1 + total_damage) * (1 + total_defense) * (1 - total_oppdmg)
    dmg_change = ((1 + total_damage) * (1 - total_oppdmg) - 1) * 100
    dmg_taken_change = ((1 / (1 + total_defense)) - 1) * 100

    return skillmod, dmg_change, dmg_taken_change, None


@bot.command()
async def skillmod(ctx, *args):
    hero_input = {}
    try:
        for i in range(0, len(args), 2):
            hero = args[i]
            count = int(args[i + 1])
            hero_input[hero] = count
    except:
        await ctx.send("❌ Usage example: `!skillmod Amane 2 Hilde 1 Saul 1`")
        return

    skillmod, dmg, defp, err = calculate_skillmod(hero_input)

    if err:
        await ctx.send(f"❌ Unknown hero: **{err}**\nType `!heroes` for list.")
        return

    await ctx.send(f"✨ **SkillMod:** `{skillmod:.4f}`\n"
                   f"⚔️ **Damage:** `{dmg:+.2f}%`\n"
                   f"🛡️ **Damage Taken:** `{defp:.2f}%`")


@bot.command()
async def heroes(ctx):
    hero_list = ", ".join(HERO_DATA.keys())
    await ctx.send(
        f"🦸 **Available Joiner Heroes:**\n{hero_list}\n\nUse like:\n`!skillmod Amane 2 Hilde 1 Saul 1`"
    )


bot_token = os.getenv("DISCORD_BOT_TOKEN")
if bot_token:
    bot.run(bot_token)
else:
    print("Error: DISCORD_BOT_TOKEN not found in environment variables.")
    print("Please add your Discord bot token to the Secrets.")
