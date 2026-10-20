# FamilyOS for Home Assistant

A Home Assistant integration for [FamilyOS](https://github.com/onurceri/family-os), the self-hosted family organizer.
It brings the family's calendar, shopping lists, tasks and chores into Home Assistant, and lets Home Assistant add to
them. It talks to FamilyOS with an app key through FamilyOS's public API, so it only does what the key's role allows.

- Needs FamilyOS **0.3.0 or newer** and Home Assistant **2026.10 or newer**.
- Polls FamilyOS (local polling, every 60 seconds by default). Asking is cheap: FamilyOS says what changed, and the
  integration reads only that.

## Install

### With HACS (custom repository)

1. In HACS, open the menu (three dots), **Custom repositories**.
2. Add `https://github.com/onurceri/familyos-homeassistant` with the category **Integration**.
3. Find **FamilyOS** in HACS, download it and restart Home Assistant.

### By hand

Copy the `custom_components/familyos` folder into your Home Assistant `config/custom_components` folder and restart.

## Set up

1. **In FamilyOS**, as an admin, open **Settings, You, Connected apps** and press **Add an app**.
   - **Name**: "Home Assistant".
   - **Role**: what Home Assistant may do. A **Guest** app can only look (the entities show, but changes are
     refused). A **Member** app can change what a member can. Pick a role of your own to allow less.
   - **What happens to its changes**:
     - *Changes apply*: what the role allows happens at once. Choose this for a Home Assistant you trust.
     - *Changes wait for approval*: every change becomes a suggestion that a person approves in FamilyOS first. Choose
       this if an AI sits behind Home Assistant (a voice assistant, say).
   - **May act for**: leave empty unless you want to use *Act for* below.
   - Copy the key when it appears. It is shown once.
2. **In Home Assistant**, open **Settings, Devices & services, Add integration**, choose **FamilyOS**, and enter your
   FamilyOS address (for example `http://192.168.1.20:3000` or `https://family.example.com`) and the key.
   Use an IP address or a real host name: `.local` names do not always resolve from Home Assistant's container.

If FamilyOS later refuses the key (revoked, expired, app paused), Home Assistant asks for a new one: **Repair** on the
integration, then enter the new key.

## What you get

One device, **FamilyOS**, with:

| Entity | What it does |
|---|---|
| `calendar.familyos_calendar` | The family calendar. Shows events (repeating ones expanded), and can add, change and delete events, including one date of a repeating event. Its state is the event on now, or the next one. |
| `todo.familyos_shopping_<list>` | One for each shopping list. Add items, rename them, tick them off and put them back, delete them. Items keep their FamilyOS ids. New lists get their entity at the next poll. |
| `todo.familyos_tasks` | The family's tasks. Add, rename, set a due date (or date and time) and notes, complete, reopen and delete. |
| `sensor.familyos_chores_due_today` | How many chores are due today. The titles are in the `chores` attribute. |
| `sensor.familyos_chores_overdue` | How many chores are late, with their titles in `chores`. |

An entity becomes **unavailable** (not an error) when FamilyOS cannot be reached, when its feature is switched off in
FamilyOS (**Settings, Features**), or when the app's role may not use it.

### Services

- `familyos.post_note`: puts a note on the family board. Fields: `text`, `pinned`.
- `familyos.complete_chore`: marks a chore done. Fields: `chore` (its title or id), `due_date` (default: the date it
  is due), `done_by` (the id of the member who did it).

Both can say which FamilyOS to use with `config_entry_id` when you have more than one, and both return
`{status: applied | drafted, ...}` when called with a response.

An app is nobody, so FamilyOS needs to know whose chore it was: give `done_by`, or set **Act for** (below).

### Options

**Settings, Devices & services, FamilyOS, Configure**:

- **How often to ask FamilyOS**: 15 to 3600 seconds, 60 by default.
- **Act for**: the id of a family member this app may act for (it starts with `member_`; the app's *May act for* list
  in FamilyOS must include them). When set, every call is made **as that person**: it can do only what both the
  person and the app's role allow, their own things stay theirs (a chore marked done counts as theirs), and a
  supervised person's changes wait for approval. Left empty, the **app's own role** applies and nothing is done as
  anyone.

## When a change waits for approval

If the app is in *Changes wait for approval* mode, or acts for a supervised person, FamilyOS does not make the change.
It becomes a suggestion for a person to approve. Home Assistant then:

- shows a persistent notification, **"Waiting for approval in FamilyOS: Milk"**, and writes the same to the log;
- **keeps the item as it was**: an item you tried to add does not appear, one you ticked off stays open, until a
  person approves the suggestion in FamilyOS and the next poll brings the result.

## Limits

- Changing **how an event repeats**, and changing or deleting **"this and following"** events, are refused from Home
  Assistant with a message. Change those in FamilyOS. Adding a repeating event (daily, weekly on chosen days, monthly,
  with an interval and an end date) works; other rules (`COUNT`, yearly, ...) are refused.
- A date of a repeating event that was moved in FamilyOS is an event of its own there, and shows and changes that way.
- Shopping quantities and categories are not shown or set; an item is its title.
- There is no sensor for waiting suggestions: FamilyOS's API lets an app follow its own suggestion but not list them.

## Privacy and safety

The key is kept in Home Assistant's config entry (in `.storage` and in Home Assistant backups). Keep it as you keep
any token. A leaked key can do no more than the app's role allows, and never anything only people do (approving
suggestions, managing people, keys or devices); revoke it in FamilyOS at once. Home Assistant never sends data
anywhere except to the FamilyOS address you gave.

## Development

```bash
uv venv --python 3.14 .venv && source .venv/bin/activate
uv pip install -r requirements_test.txt
ruff check . && ruff format --check . && mypy custom_components/familyos
pytest tests
```

The tests mock the client ([familyos-client](https://github.com/onurceri/familyos-client)); nothing needs a running
FamilyOS.

## License

AGPL-3.0-or-later, the same as FamilyOS.
