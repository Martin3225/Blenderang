<p align="center">
  <img src="docs/icon.png" width="128" alt="Blenderang icon">
</p>

<h1 align="center">Blenderang</h1>

<p align="center">
  <b>Throw your Godot scene into Blender. Catch it back.</b><br>
  Open your Godot scene in Blender with one click, move things around and reshape models,<br>
  then send it all straight back to Godot.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Godot-4.7-478cbf?logo=godotengine&logoColor=white" alt="Godot 4.7">
  <img src="https://img.shields.io/badge/Blender-5.2-e87d0d?logo=blender&logoColor=white" alt="Blender 5.2">
  <img src="https://img.shields.io/badge/license-MIT%20%2B%20GPL--3.0-green" alt="License">
</p>

<!-- TODO: replace with a GIF: click "Blender" in Godot → move a crate → "Send to Godot" -->
<p align="center"><img src="docs/demo.gif" width="720" alt="Blenderang demo"></p>

---

## Why

Godot is great for building the game, and Blender is great for arranging and
shaping the world. Moving between them usually means exporting, importing and
fixing things by hand. Blenderang makes it a round trip that starts and ends
in Godot:

1. In Godot, click **Blender**. Your scene opens in Blender, fully built.
2. Move objects, reshape models, add new ones.
3. Click **Send to Godot**. The scene updates in the editor, ready to play.

It's made for **whiteboxing and modelling inside your real game levels**.
Instead of building a model in an empty Blender file and guessing how it will
fit, you shape it right where it stands, surrounded by the actual level from
Godot: terrain, buildings, characters and all.

What you get:

- **Lay out scenes in Blender.** Move, rotate, scale, duplicate and delete
  objects, then send the new layout back to the `.tscn`.
- **Edit models in context.** Open a model's source `.blend` with the rest of
  the level around it, edit it, press `Ctrl+S`, and the `.glb` is re-exported
  and reimported by Godot.
- **No source `.blend`? No problem.** *Make source* turns any `.glb` into an
  editable `.blend` next to the asset.
- **The `.tscn` stays the truth.** Blender never saves its own copy of the
  scene, so nothing can drift out of sync and `git pull` never breaks it.
- **One undo.** Each import from Blender is a single undo step in Godot.
- **Terrain3D preview.** Your [Terrain3D](https://github.com/TokisanGames/Terrain3D)
  terrain shows up in Blender with a baked colour map, so you can place things
  on it. It's read-only: you can't sculpt or paint the terrain in Blender.
- **Safe for teams.** People who don't use Blender don't need to do anything.
  The game still uses only `.glb` / `.fbx`.

## Requirements

| | version |
|---|---|
| Godot | 4.7 (tested) |
| Blender | 5.2 (tested) |
| OS | Windows and Linux. macOS is untested. |

## Installation

Blenderang has two parts: a **Godot editor plugin** and a **Blender
extension**. You need both.

### 1. Godot plugin

**From the Asset Library (easiest):** in Godot open the **AssetLib** tab,
search for *Blenderang*, click **Download**, then **Install**.

**Manually:** download `blenderang-godot-x.y.z.zip` from the
[latest release](https://github.com/Martin3225/Blenderang/releases/latest) and
unzip it into your project's root folder (it contains `addons/blenderang/`).

Then:

1. Enable it in `Project ▸ Project Settings ▸ Plugins`.
2. Set the path to Blender in
   `Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸ Blender Path`.
   This is the same setting Godot uses for importing `.blend` files, so you
   may already have it.

| Blender installed from | typical path |
|---|---|
| Windows installer | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| Windows, Steam | `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe` |
| Linux package / AUR | `/usr/bin/blender` |
| Linux, Steam | `~/.local/share/Steam/steamapps/common/Blender/blender` |
| Linux, Flatpak | `/var/lib/flatpak/exports/bin/org.blender.Blender` |

> **Keep Godot's own `.blend` import off.** Blenderang works with `.glb` /
> `.fbx`. If `filesystem/import/blender/enabled` is on, projects will show
> errors on machines without Blender.

### 2. Blender extension

1. Download `blenderang-blender-x.y.z.zip` from the
   [latest release](https://github.com/Martin3225/Blenderang/releases/latest).
2. In Blender: `Edit ▸ Preferences ▸ Get Extensions ▸ ⌄ ▸ Install from Disk…`
   and pick the zip. Don't unzip it.
3. Make sure **Blenderang** is enabled under `Add-ons`.

<details>
<summary>For developers: link the extension from a git clone</summary>

So that `git pull` updates it.

**Windows** (Command Prompt as administrator):

```bat
mklink /J "%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\blenderang" "C:\path\to\Blenderang\tools\blenderang"
```

**Linux:**

```sh
ln -sfn "$PWD/tools/blenderang" ~/.config/blender/5.2/extensions/user_default/blenderang
# Flatpak
ln -sfn "$PWD/tools/blenderang" ~/.var/app/org.blender.Blender/config/blender/5.2/extensions/user_default/blenderang
```

Then in Blender: `Edit ▸ Preferences ▸ Add-ons ▸ ⌄ ▸ Refresh Local` and
enable **Blenderang**.

To build both release zips yourself: `python tools/build_release.py`
(writes them to `dist/`).

</details>

## Quick start

A five-minute tour: move a prop, then edit its model.

### Move things around

1. Open a 3D scene in Godot that contains some `.glb` or `.fbx` models.
2. Click the **Blender** button in the 3D editor toolbar (next to
   *Transform* and *View*).
   You can also right-click the scene tab, or a `.tscn` in the FileSystem
   dock, and choose **Open in Blender**.
3. Blender opens and builds the scene by itself. Press `N` and open the
   **Blenderang** tab.
4. Move, rotate or duplicate (`Shift+D`) a few models.
5. Click **Send to Godot**.
6. Switch back to Godot. The scene updates within a second. Don't like it?
   `Ctrl+Z` undoes the whole import.

### Edit a model

1. In the Blenderang panel, find the model in the **Models** list (the search
   box matches the name, the node path and the asset file).
2. If it says **Pick source**, the model has no `.blend` yet. Pick an existing
   one, or select the model, press `Tab` and choose **Make source**: this
   creates `model.blend` next to `model.glb` (or in the models folder, see
   below), ready for editing.
3. Click **Edit** (or `Tab` ▸ **Edit model**). The model's `.blend` opens with
   the rest of the level around it as locked context, so you can see how it fits.
4. Change the model, then press `Ctrl+S`. The `.blend` is saved and the `.glb`
   is re-exported. Godot reimports it on its own.
5. Click **Save and return to scene** to go back to the layout.

That's it.

To edit a model without a scene, right-click its `.glb` / `.fbx` in Godot's
FileSystem dock and choose **Open source in Blender**. `Ctrl+S` there
re-exports the asset into your project the same way. A model Godot finds no
source for offers only **Pick source .blend…** there; the file dialog starts at
the asset's mirrored path in the models folder.

A source stays linked to its asset after **Save and return to scene**: the
link is stored in the `.blend` itself. Reopening it by hand with Blenderang
enabled still re-exports on `Ctrl+S`, without restoring the old scene context.
The **Auto save to Godot** switch in the panel turns the export on save off and
on again for the whole file; it's saved in the `.blend`, so it's the same for
everyone. **Export now** exports without saving.

### Export a new model

A `.blend` you made yourself, not from Godot, can export into the game too:

1. Save it in the models folder (or in the Godot project).
2. In the Blenderang panel, click **Link to Godot** (export with **Export now**)
   or **Auto save to Godot** (`Ctrl+S` exports too). It offers the Godot
   project, the models folder and the `.glb`, all editable and with a file
   browser: the project folder + `assets/` + the file's path in the models
   folder (`<models folder>/props/lamp.blend` → `res://assets/props/lamp.glb`;
   next to the `.blend` when it lies in the project itself). Outside the
   models folder the path is only a guess from the file's name, and the
   dialog says so. The models folder you set here is saved for the Godot
   project, only for you, and Godot uses it too.
3. The active collection gets a glTF exporter (with *Apply modifiers* on). If
   the Scene Collection is active, a collection named after the file is
   created and the scene's objects move into it.

The panel shows what the export means in Godot: whether the `.glb` already
exists (and gets overwritten) and whether Godot finds this `.blend` as its
source, so **Edit** in Godot opens it. Godot finds a source by name, so when it
doesn't find this `.blend` (another name, Save As, several models in one file),
the export writes `<asset>.bbsrc` pointing at it. That works for a `.blend` in
the project or the models folder; one elsewhere gets a warning. An asset whose
source is another `.blend` keeps it, with a warning that the export overwrites it.

Blender knows a Godot project once it has opened it from Godot; you can also
add or remove projects in `Preferences ▸ Add-ons ▸ Blenderang`. The `assets`
folder is a project setting, `Project Settings ▸ Blenderang ▸ Models ▸ Project
Folder`; leave it empty if the models folder mirrors the whole project.

### What is shared and what is yours

Only where the repositories are on your disk is personal; everything else is
shared through the files:

| what | where | shared |
|---|---|---|
| Godot projects on this disk | Blender config, `blenderang_projects.json` | no |
| models folder on this disk | `.pipeline/local/settings.json` in the Godot project | no |
| sources outside both repositories | `.pipeline/local/sources.json` | no |
| the asset a model exports to (`res://…`) and its Godot uid, the Godot project's name, Auto save | the `.blend`, on the model's collection | yes |
| the exporter's path | the `.blend`, relative to it (`//…`) | yes |
| a source picked by hand | `<asset>.bbsrc` | yes |

A `.blend` finds its Godot project by where it lies (in the project or its
models folder), otherwise by the project's name. While you edit a model from a
scene, Blender keeps the scene to return to in `blenderang_edit.json`; the
entry is removed when you return.

### Moving and renaming files

- **A `.glb` in Godot's FileSystem dock** (a single file or a whole folder):
  its source follows. Its `.bbsrc` and personal pick move with it, and when
  Godot wouldn't find the source at the new path (renamed asset, a `.blend`
  left next to the old place), a `.bbsrc` there points to it. The `.blend`
  learns about it when it opens, saves or exports: it keeps Godot's uid of the
  asset (from its `.import`) and finds the asset under its new path, instead of
  recreating it at the old one. The uid is recorded once Godot has imported the
  asset and the `.blend` was opened or saved after that.
- **A `.blend`** (file manager, `git mv`, Save As): it keeps exporting to the
  same asset. If Godot no longer finds it by name, the next export writes a
  `.bbsrc`. After Save As the old file remains Godot's source until you delete it.
  A personal source (outside the project and the models folder) has to be
  picked again.
- **A collection** in Blender: its name doesn't matter. Don't nest one model's
  collection inside another's: the outer `.glb` would contain both.

## How it works

### What you can move

On first use, Blenderang marks the art instances in your scene (`.glb` /
`.fbx` models) with a `bb_id` metadata entry. **Only nodes with `bb_id` are
ever changed by Blender.** Gameplay scenes (like `Player.tscn`), anything
under a physics body, and the insides of other instanced scenes are left
alone.

In Blender's outliner you'll see:

- **`BB_Layout`**: models you can move, rotate, scale, duplicate and delete.
  A model that is a child of another model in Godot (gear on a character) is
  its child in Blender too, so it moves with its parent.
- **`BB_Locked`**: real geometry of everything else in the scene (characters,
  buildings, terrain, lights, markers). You can select it and focus on it,
  but not move it.

Objects you add in Blender without a `bb_id` are helpers. They aren't sent to
Godot and disappear the next time you open the scene.

Mark or unmark nodes manually with
`Project ▸ Tools ▸ Blenderang ▸ Mark selection / Unmark selection`.

### Where model sources live

Blenderang looks for the source `.blend` **next to the asset, with the same
name**:

```
levels/castle/castle.glb     ← used by the game
levels/castle/castle.blend   ← source for editing
```

#### Shared models folder

If your team keeps the source `.blend` files in their own folder outside the
game project (for example a separate git repository), tell Blenderang where
that folder is on your disk:

- in Godot: `Project ▸ Tools ▸ Blenderang ▸ Set models folder…`
- in Blender: **Models folder** at the bottom of the Blenderang panel

Everyone can keep the folder somewhere else; the location is saved only for
you (`.pipeline/local/settings.json`). When a model has no `.blend` next to its
asset, Blenderang searches the folder for `<asset name>.blend` at any depth
(case-insensitive, hidden folders like `.git` skipped). If several files have
that name, the one at the asset's mirrored path wins, otherwise the first
alphabetically, and Blender warns about it.

The models folder mirrors the project's `assets/` folder (set in
`Project Settings ▸ Blenderang ▸ Models ▸ Project Folder`): the mirrored path
of `res://assets/levels/castle/castle.glb` is
`<models folder>/levels/castle/castle.blend`. Assets outside `assets/` keep
their whole path (`res://levels/castle.glb` → `<models folder>/levels/castle.blend`).

With a models folder set, **Make source** creates the new `.blend` in it, at
the mirrored path, instead of next to the asset in the game project.

#### Picking a source by hand

If your source is somewhere else, pick it by hand with **Pick source** in
Blender (model list, **Detail** or `Tab` on the model), or in Godot with
`Project ▸ Tools ▸ Blenderang ▸ Pick source .blend for selection…` or
**Pick source .blend…** on a model in the FileSystem dock. The file browser
starts in the models folder when one is set.

| where the picked `.blend` is | stored in | who sees it |
|---|---|---|
| inside the project | `<asset>.bbsrc` next to the asset | everyone, via git |
| inside the models folder | `<asset>.bbsrc` as `models://<path in the folder>` | everyone who has the folder set |
| anywhere else | `.pipeline/local/sources.json` | only you |

The order is: your personal pick, then `<asset>.bbsrc`, then the `.blend` next
to the asset, then the name search in the models folder.

### Export settings

A model in a `.blend` is a **collection with a glTF exporter** (Blender's own
Collection Exporter, `Properties ▸ Collection ▸ Exporters`). The exporter's path
decides which asset it is; the collection can have any name. Blenderang
doesn't add settings of its own: what you set in the exporter is what's
exported, and it's saved in the `.blend`. The panel lists the file's models
with the `.glb` each exports to; the folder button next to it picks another
file in the Godot project (a model without a path shows **Set path…**). Click a
model to show its exporter with all of Blender's glTF options, including
**Export All** to re-export without saving. This works for a collection
excluded from the view layer too, which Blender can't make active.

Blender's glTF add-on hides *Include ▸ Limit to* for collection exporters, yet
the exporter still honours *Selected*, *Visible* and *Renderable Objects*;
the panel shows these three below the exporter. *Active Collection* and
*Active Scene* don't apply: the collection is what gets exported.

The exporter's path is absolute and differs on every disk, so Blenderang also
stores it on the collection as a `res://` path and points the exporter at the
project wherever it lies on your disk when the file opens.

*Apply modifiers* is on for every exporter of a linked `.blend`, so booleans
end up in the `.glb`: the ones Blenderang adds and the ones you add in Blender's
Collection Exporters (switched on when the file opens or saves). Once you set it
yourself, it stays as you set it.

**Several models in one `.blend`:** give each its own collection with its own
exporter. `Ctrl+S` exports all of them, and each asset in Godot links the
collection that exports it. Several exporters on one collection export the
same model several times (say `.glb` and `.fbx`). A duplicated collection
gets no path (Blender clears it): set its own with **Set path…**. The panel
warns when two models export the same file.

Helper objects that shouldn't end up in the `.glb` (boolean cutters, guides)
go in a separate collection without an exporter, *next to* the model
collection, not inside it. Modifiers still use them, and they don't show up
when the model is linked into a scene.

Sources from before this worked by the collection's name: if no exporter
writes the asset, the collection named after it (`crate` for `crate.glb`) is
used, otherwise the first one, and it gets an exporter when you edit it.

> **Shape keys:** glTF export drops shape keys on meshes that have
> modifiers when *Apply modifiers* is on. Turn it off for that model if you
> need them.

### Terrain3D (preview only)

Blenderang is partially compatible with
[Terrain3D](https://github.com/TokisanGames/Terrain3D). The terrain is baked
to a mesh plus a top-down colour map so you can see it and place things on it
in Blender. It's locked there: changes to the terrain itself are never sent
back, so keep sculpting and painting in Godot.
Resolution is set in `Project Settings ▸ Blenderang ▸ Terrain`:

| setting | default | options |
|---|---|---|
| `mesh_spacing_m` | 8 m | 1, 2, 4, 8, 16, 32 m |
| `texture_size` | 2048 px | 1024 – 8192 px |

The bake is cached and only redone when the terrain or settings change.

### Files Blenderang creates

Everything lives in `.pipeline/` in your project (it has a `.gdignore`):

| file | what |
|---|---|
| `<scene>.json` | manifest: ids and transforms of the scene's nodes |
| `<scene>.context.glb` | locked context geometry for Blender |
| `<scene>.terrain.*` | terrain bake cache |
| `local/` | your personal settings, never committed |

You can commit `.pipeline/` or ignore it. Everything in it can be rebuilt.

## Limitations

- Grass and trees placed with MultiMesh (e.g. ProtonScatter) aren't shown in
  Blender.
- *Make source* goes through `.glb`, so it keeps meshes, UVs, armatures and
  basic materials, but not shader node setups or modifiers.
- Terrain3D terrain is a read-only preview in Blender, shown as an unlit
  colour map because its shader can't be reproduced there.
- macOS is untested. Windows isn't covered by the automated GUI tests.

## Troubleshooting

| problem | fix |
|---|---|
| Clicking **Blender** does nothing | Check the Blender path in Editor Settings. |
| Blender opens but the panel says to open a scene from Godot | The Blender extension isn't enabled, or the versions don't match. |
| A model shows as an empty axis | Its `.glb` failed to load. The panel lists the error in red. |
| My edits didn't come back to Godot | Only nodes with `bb_id` are updated. Check that the node is marked. |

## Running the tests

```sh
python tests/run_tests.py                  # everything, ~40 s
python tests/run_tests.py --only blender   # one suite
python tests/run_tests.py --regen-fixtures # regenerate test scenes
```

You need Python 3, Godot and Blender (on `PATH`, in `$GODOT` / `$BLENDER`, or
passed with `--godot` / `--blender`). On Linux the GUI suite needs `Xvfb`.
Tests run in an isolated copy under `tests/.work` with their own Godot and
Blender config, so they never touch your settings or your game project.

## Releasing

1. Set the same version in `addons/blenderang/plugin.cfg` and
   `tools/blenderang/blender_manifest.toml`.
2. Commit, tag and push: `git tag vX.Y.Z && git push github main vX.Y.Z`.

The [Release workflow](.github/workflows/release.yml) builds
`blenderang-godot-X.Y.Z.zip` and `blenderang-blender-X.Y.Z.zip` and attaches
both to the GitHub release of the tag. It fails if the tag and the two
versions don't match. The Asset Library serves the tagged repository itself;
`.gitattributes` keeps the tests and the Blender extension out of that download.

## Contributing

Bug reports and pull requests are welcome. Please open an
[issue](https://github.com/Martin3225/Blenderang/issues) first for anything
big. This is a small hobby project, so replies may take a while.

## License

- Godot plugin (`addons/blenderang/`): [MIT](LICENSE)
- Blender extension (`tools/blenderang/`): [GPL-3.0-or-later](tools/blenderang/LICENSE),
  as required for Blender add-ons

Blender is a trademark of the Blender Foundation. Godot is a trademark of
the Godot Foundation. Blenderang isn't affiliated with either.
