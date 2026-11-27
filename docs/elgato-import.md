# Importing profiles from the Elgato Stream Deck app

Moving from a PC with the Elgato Stream Deck app to Stream Assistant? The key editor can
read the app's profiles and turn each one into a [template](editor.md#templates). Keys of
the Home Assistant plugin, folders and page changes are taken over. Everything else stays
empty, and a report lists what was not taken over.

## Exporting from the Stream Deck app

- **One profile:** in the Stream Deck app's preferences, under *Profiles*, choose the
  profile and *Export* it from its menu. You get a `.streamDeckProfile` file.
- **All profiles:** a backup made in the app's preferences is a
  `.streamDeckProfilesBackup` file with every profile of every deck.

Menu names differ a little between app versions.

Both are read the same way. Profiles of the app before version 6, of 6.x and of 7.x work.
The file may be up to 64 MB.

## Importing

1. Open **Stream Assistant** in the sidebar (administrators only).
2. Click the import button next to **+ Template** (*Import Elgato profile*) and choose the
   file. Then click *Read file*.
3. The dialog lists the profiles in the file, with their pages, folders and how many keys
   use Home Assistant. For each profile you want, keep it ticked, give the template a name
   and check the model. The model the profile was made for is suggested. You can choose
   another one: keys keep their row and column, and keys that do not fit are listed.
4. Click *Import*. A template is created for each chosen profile. The report shows what
   was not taken over and what was changed. *Copy report* puts it on the clipboard.
   *Open template* shows the first new template in the editor.

Link a deck to the template (*Assign template …*), or use *Detach* afterwards to give the
deck its own copy.

## What is taken over

| In the Stream Deck app | In Stream Assistant |
|---|---|
| First page | Root page |
| Further pages | Folders of the root page; key 1 of a folder is always *back*, so a key there moves to the next free key |
| Folder (*Create Folder*) and its key | Folder below the page that opens it, and a key that opens it, with the folder key's title |
| *Back* in a folder | The folder's own back key |
| *Next page*, *Previous page*, *Go to page* | A key that opens that page |
| Home Assistant plugin key (*Entity*) | Entity, title, actions for press and long press (the plugin's service with its data, the key's entity as target) |
| Home Assistant plugin on a dial (Stream Deck +) | Entity and press. Turning becomes *Adjust* when the entity can be adjusted (light, cover, fan, media player, climate, number, select) |
| Multi action with one Home Assistant step (and delays) | That step |
| Custom image of a key that is taken over | Saved in `/config/www/stream_assistant/import/<folder>/` and used as the key's image |

The Home Assistant plugin meant here is
[Home Assistant by Christoph Giesche](https://github.com/cgiesche/streamdeck-homeassistant),
the one in the Elgato Marketplace. All its settings versions are understood. Its server
address and token are not part of a profile and are not needed.

A page that no key leads to (in the app you can swipe between pages) gets a key on the page
before it, with an arrow and the page's name. The Stream Deck Neo's page buttons turn the
pages in the editor's order too.

## What is not taken over

These keys stay empty and are listed in the report as *not taken over*:

- Actions of other plugins and of the app itself: hotkeys, opening apps or websites, text,
  media keys, sound and so on. Their icons and images are not imported.
- Multi actions with more than one step, and multi actions with steps that are not Home
  Assistant.
- *Switch profile*: a deck shows one template at a time.
- Keys and dials that do not fit the chosen model.

These are taken over with a change and listed as *taken over with changes*:

- Actions whose data uses a template such as `{{ ticks }}`: the key keeps its entity, but
  not this action. Set it again in the editor.
- Titles that are templates (other than the friendly name): the automatic title is used.
- A dial whose tap has its own action besides the press: the tap runs the press action, as
  everywhere in Stream Assistant.
- Turning a dial: Stream Assistant adjusts the entity by its own steps instead of calling
  the plugin's service.
- Entities that this Home Assistant does not have: they are kept, so the key works once the
  entity exists. Check the name if it was renamed.
- Images in other formats than PNG, JPEG, GIF, BMP or WebP, or larger than 2 MB.

## Good to know

- The import always creates new templates and never changes an existing one or a deck.
  Importing the same file again creates another template.
- Images stay in `/config/www/stream_assistant/import/` when the template is deleted. Files
  below `/config/www` can be fetched under `/local/` without signing in, so do not import
  profiles whose key images show something private.
- The uploaded file is kept in memory for 15 minutes so you can import it again with another
  model; it is not written to disk.
