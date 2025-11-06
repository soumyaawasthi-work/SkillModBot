# Discord Skill Modifier Bot

## Overview
A Discord bot that calculates skill modifiers for a game based on hero team compositions. The bot analyzes hero combinations and their multiplier effects to provide detailed damage and defense calculations.

**Current Status**: Two bots running - text commands (main.py) and slash commands (bot.py)

## Recent Changes
- **2025-11-06**: Added slash command bot (bot.py)
  - Modern slash commands with autocomplete
  - Rich embeds with user-friendly summaries
  - Commands: `/skillmod`, `/hero`, `/help_skillmod`, `/compare`
  - Supports up to 6 hero slots per calculation
  - Optional guild-specific registration for instant testing
- **2025-11-05**: Initial project setup
  - Created Discord bot with `!skillmod` text command
  - Added hero database with 12 heroes and their multiplier effects
  - Set up secure token management via environment variables
  - Configured Python environment with discord.py and python-dotenv

## Project Architecture

### Structure
```
.
├── main.py              # Text-based Discord bot (!commands)
├── bot.py               # Slash command bot (/commands) - NEW!
├── requirements.txt     # Python dependencies
├── .env.example        # Template for environment variables
├── .gitignore          # Python gitignore
└── replit.md           # This file
```

### Two Bot Versions

**main.py** - Classic text commands:
- Uses `!` prefix commands (e.g., `!skillmod Chenko 4`)
- Requires "Message Content Intent"
- Simple text-based responses
- Good for quick calculations

**bot.py** - Modern slash commands (NEW):
- Uses `/` slash commands (e.g., `/skillmod hero1:Chenko count1:4`)
- No special intents required
- Beautiful embed responses with summaries
- Autocomplete for hero names
- Additional commands: `/hero`, `/compare`, `/help_skillmod`
- Supports up to 6 hero slots

### Heroes and Effects
The bot includes 12 heroes with different multiplier effects:

**Damage Up Heroes:**
- Chenko, Amadeus, Yeonwoo (101: 37.5% bonus each)
- Amane, Margot (102: 25% bonus each)

**Defense Up Heroes:**
- Howard, Quinn (111: 33.3% bonus each)
- Gordon (113: 50% bonus)
- Saul (112 + 113: 37.5% + 50% bonuses)
- Hilde (112 + 102: 37.5% defense + 25% damage)

**Opponent Damage Down Heroes:**
- Fahd (201: 25% reduction)
- Eric (202: 37.5% reduction)

### Bot Commands
- `!skillmod [Hero Count] [Hero Count] ...`
  - Example: `!skillmod Chenko 2 Hilde 1`
  - Calculates and displays:
    - **SkillMod**: Combined multiplier value
    - **Damage**: Percentage change in damage output
    - **Damage Taken**: Percentage change in damage received

### Calculation Formula
- SkillMod = (1 + total_damage) × (1 + total_defense) × (1 - total_opponent_damage_down)
- Damage Change = (damage_bonuses - opponent_damage_down) × 100
- Defense Change = ((1 / (1 + defense_bonuses)) - 1) × 100

## Setup Instructions

### 1. Get a Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a New Application
3. Go to the "Bot" section and create a bot
4. Copy the bot token
5. Enable "Message Content Intent" under Privileged Gateway Intents

### 2. Add Token to Replit Secrets
1. In Replit, open the Tools panel
2. Navigate to Secrets
3. Add required secret:
   - Key: `DISCORD_BOT_TOKEN`
   - Value: [paste your bot token]
4. **Optional** - For faster slash command testing, add:
   - Key: `GUILD_ID`
   - Value: [your Discord server ID]
   - Note: Right-click your server → Copy Server ID (requires Developer Mode enabled)

### 3. Invite Bot to Your Server

**For text commands (main.py):**
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=2048&scope=bot
```

**For slash commands (bot.py):**
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=2048&scope=bot%20applications.commands
```

### 4. Run the Bot
The bot will automatically start when you run the project. Look for the message:
```
[BotName] has connected to Discord!
```

## Dependencies
- **discord.py** (>=2.3.0): Discord API wrapper for Python
- **python-dotenv** (>=1.0.0): Environment variable management
