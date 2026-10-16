# Blender Bridge

Rozmisťování objektů Godot scény v Blenderu a zpět. Přenáší se jen identity
a transformace, nikdy geometrie — ta zůstává v `.glb` (pro hru) a volitelně
v `.blend` (zdroj pro úpravy).

Cíl: Godot 4.7, Blender 5.2, priorita Windows.

```
addons/blender_bridge/   Godot editor plugin
tools/blender_bridge/    Blender extension
```

---

## Pro tým: co se mění

**Kdo nepoužívá Blender, nemusí dělat nic.**

- Hra dál používá jen `.glb` / `.fbx`. Projekt jde otevřít bez Blenderu.
- `project.godot` má `filesystem/import/blender/enabled=false`, takže Godot
  `.blend` soubory ignoruje, ať leží kdekoli. **Nezapínat** — jinak začne
  projekt na strojích bez Blenderu hlásit chyby.
- Scény se mění jen o metadatum `bb_id` na nodech, které jdou z Blenderu
  posouvat.

---

## Instalace

### Godot

Zkopíruj `addons/blender_bridge/` do projektu a zapni v
`Project ▸ Project Settings ▸ Plugins`.

V `Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸ Blender Path` nastav cestu
k Blenderu. Je to stejné nastavení, které Godot používá pro import `.blend`,
takže ho možná už máš.

| odkud | cesta |
|---|---|
| Windows, instalátor | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| Windows, Steam | `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe` |
| Linux, balíček / AUR | `/usr/bin/blender` |
| Linux, Steam | `~/.local/share/Steam/steamapps/common/Blender/blender` |
| Linux, flatpak | `/var/lib/flatpak/exports/bin/org.blender.Blender` |

### Blender

Rozšíření se připojí odkazem z repa, ať se aktualizuje s `git pull`.

**Windows** (příkazová řádka jako správce):

```
mklink /J "%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\blender_bridge" "C:\cesta\k\repu\tools\blender_bridge"
```

**Linux:**

```sh
# balíček, AUR, Steam
ln -sfn "$PWD/tools/blender_bridge" ~/.config/blender/5.2/extensions/user_default/blender_bridge
# flatpak (má vlastní XDG_CONFIG_HOME)
ln -sfn "$PWD/tools/blender_bridge" ~/.var/app/org.blender.Blender/config/blender/5.2/extensions/user_default/blender_bridge
```

Pak v Blenderu `Edit ▸ Preferences ▸ Add-ons ▸ ⌄ ▸ Refresh Local` a zaškrtni
**Blender Bridge**. Jednou, napořád.

Bez odkazu: `blender --command extension build --source-dir tools/blender_bridge`
a zip přes `Install from Disk`.

---

## Použití

Jeden klik na každé straně.

**Godot → Blender**, kterékoli z:

- tlačítko **Blender** v liště 3D editoru (vedle *Transform*, *View*),
- pravé tlačítko na **tabu scény** ▸ *Otevřít v Blenderu*,
- pravé tlačítko na **`.tscn` ve FileSystemu** ▸ *Otevřít v Blenderu* — scénu
  nejdřív otevře, když není aktivní.

Při prvním použití označí art instance (`.glb/.fbx`), pak uloží scénu, zapíše
manifest a spustí Blender, který si scénu postaví bez dalšího klikání.

**Blender → Godot:** velké tlačítko **Odeslat do Godotu** v `N ▸ Bridge`.
Godot si změnu všimne do sekundy a načte ji do otevřené scény jako jednu undo
akci — `Ctrl+Z` ji vrátí.

Scéna v Blenderu **nemá vlastní `.blend` a nic se neukládá**. Pravdou
o rozmístění je vždycky `.tscn`; Blender je jen editor nad ní a pokaždé se
postaví znovu z manifestu. Nemůže se tak rozejít s Godotem a `git pull` nic
nerozbije. **Zahodit změny** postaví scénu znovu z posledního odeslaného stavu.

V Blenderu vidíš:

- `BB_Layout` — objekty, se kterými můžeš hýbat, duplikovat (`Shift+D`) a mazat.
- `BB_Locked` — drátěné krabice pro všechno ostatní ze scény: hráč, terén,
  světla, spawnpointy. Nejdou vybrat; jsou tu kvůli kontextu.
- `BB_Sources` — geometrie, na kterou instance ukazují. Skrytá; zobrazí se
  tlačítkem **Zobrazit zdroje**.

Objekty bez `bb_id` se do Godotu neposílají — pomocná geometrie ve hře
neskončí. Protože se scéna neukládá, při dalším otevření z Godotu zmizí.

### Kdo smí s čím hýbat

Blender zapisuje **jen do nodů s metadatem `bb_id`**. To, že je něco instance
scény, nestačí — `Player` je taky instance a zůstává zamčený. Hromadné
označování vynechává vnitřnosti cizích instancí a cokoli pod fyzikálním
tělesem (to jsou gameplay celky).

Ručně: `… ▸ Pokročilé ▸ Označit výběr / Zrušit označení`. Node s metadatem
`bb_pinned` import přeskočí — pro objekt doladěný v Godotu.

---

## Zdroje geometrie

Zdrojový `.blend` leží **vedle** assetu se stejným názvem:

```
scenes/demo_scene/zviretice_zamek_whitebox/zviretice.glb     ← ve hře
scenes/demo_scene/zviretice_zamek_whitebox/zviretice.blend   ← zdroj
```

Když to nesedí, zapíše se přesná cesta do `<asset>.bbsrc` vedle assetu — jeden
řádek, cesta relativně ke kořeni repa. Vytvoří ho
`Project ▸ Tools ▸ Blender Bridge ▸ Vybrat zdrojový .blend pro výběr…`.
Centrální index záměrně neexistuje, byl by to zdroj merge konfliktů.

| tier | geometrie | v Blenderu |
|---|---|---|
| `none` | jen `.glb` | naimportuje se jako náhled; posouvat jde, úpravy tvaru se neuloží |
| `library` | vlastní `.blend` vedle assetu | nalinkovaný; **Upravit model** otevře jeho soubor |

### Z náhledu upravitelný model

**Vyrobit zdroj z .glb** zapíše kolekci do nového `.blend` vedle assetu
i s nastaveným exportem do `.glb` a hned ho nalinkuje zpátky. Tier `library`.
Převod přes `.glb` zachová meshe, UV a základní materiály, ne shader node
setupy ani modifikátory — dělá se jednou.

### Úprava modelu

**Upravit model** na vybraném objektu:

1. odešle rozpracované přesuny do Godotu, ať se nic neztratí,
2. otevře zdrojový `.blend` assetu,
3. kolem modelu postaví **zamčený kontext ze scény** (`BB_Context`) — obálky
   terénu, hráče, ostatních modelů — posunutý tak, jako by model stál na
   svém místě ve scéně.

`Ctrl+S` model uloží **a přegeneruje `.glb`**; Godot ho sám reimportuje.
Kontext se před každým uložením odebere a po něm vrátí, do zdrojového souboru
se nikdy nezapíše.

**Uložit a zpět do scény** postaví scénu znovu z manifestu, už s novým modelem.

Pokud zdroj vznikl ručně a nemá nastavený export, panel místo potvrzení
„Ctrl+S přegeneruje .glb“ nabídne **Nastavit glTF export**.

---

## Manifest

`.pipeline/<scéna>.json` (+ `.last.json`, snímek pro diff). Adresář má
`.gdignore`.

```json
{
  "format": 1,
  "coord_system": "godot_y_up",
  "scene": "res://scenes/demo_scene.tscn",
  "nodes": [
    { "bb_id": "4a7f…", "owner": "blender", "name": "Zviretice",
      "path": "NavigationRegion3D/Zviretice", "parent": "NavigationRegion3D",
      "src": "res://scenes/demo_scene/zviretice_zamek_whitebox/zviretice.glb",
      "tier": "library",
      "src_blend": "scenes/demo_scene/zviretice_zamek_whitebox/zviretice.blend",
      "xform": [bx,by,bz, cx,cy,cz, dx,dy,dz, ox,oy,oz],
      "bounds": { "position": [...], "size": [...] } },
    { "owner": "godot", "name": "Terrain3D", "kind": "terrain",
      "xform": [...], "bounds": { "position": [...], "size": [...] } }
  ]
}
```

`xform` je world transform vůči kořeni scény (tři sloupce báze, pak origin)
v Godot osách. Převod do Blenderu (Z nahoru) dělá výhradně addon. Import zpět
přepočítá na lokální transformaci pod rodičem. `bounds` je obálka v lokálním
prostoru nodu — z ní se staví zamčené krabice i kontext při úpravě modelu.

---

## Testováno

Na reálné scéně (Terrain3D, ProtonScatter, 28 nodů), Godot 4.7.2 a Blender 5.2.

**Godot → Blender jedním klikem.** Přesně ten Python, který plugin předává
Blenderu, spuštěný v Blenderu 5.2: scéna se pojmenuje podle manifestu, startup
kostka zmizí, scéna má 3 assety a 14 zamčených proxy, importér po sobě
nenechá prázdné kolekce. Editor se načte s tlačítkem v liště a kontextovými
menu bez chyb.

**Blender → Godot automaticky.** Živý Godot editor se scénou otevřenou,
manifest změněný zvenku: plugin do sekundy vypsal
`z Blenderu přesunuto 1 … (Ctrl+Z vrátí)`. Manifest z dřívějška se při
startu editoru naslepo nenačetl.

**Výroba zdroje.** Scéna se postaví bez souboru, `zviretice.glb` se
naimportuje jako náhled, *Vyrobit zdroj z .glb* zapíše `.blend` vedle assetu
i s exportem a nalinkuje ho. **8/8.**

**Úprava modelu s kontextem.** *Upravit model* nejdřív odešle posun o 2 m do
manifestu, otevře zdroj, kolekce modelu je ve scéně, kontext má 16 zamčených
obálek a hráč v něm stojí ~4 m od modelu (ne stovky metrů — přepočet do
prostoru modelu sedí). `Ctrl+S` přegeneruje `.glb`, kontext se po uložení
vrátí a **do uloženého souboru se nedostal**. *Uložit a zpět do scény* vrátí
scénu bez souboru, posun přežil, marker je uklizený. **17/17.**

**Round-trip.** Bez úprav nic nemění a Godot-owned položky zůstanou bajt po
bajtu stejné, duplikace dostane nové id, smazání se propíše, *Zahodit změny*
postaví scénu znovu. **5/5.**

**Import do scény.** Přesun se zapíše jako lokální transformace pod
`NavigationRegion3D`, nový node vznikne pod správným rodičem, smazaný zmizí,
undo vrátí vše. **5/5.**

Netestováno klikáním v GUI obou programů a na Windows.

---

## Rozhodnutí: scéna nemá `.blend`

Layout scény jako `.blend` byl zrušen. Pravdou o rozmístění je `.tscn`,
Blender je jen editor nad ní.

- Nemůže se rozejít s Godotem, `git pull` nic nerozbije, žádný binární soubor
  na scénu, který může držet jen jeden člověk, o krok méně (nic se neukládá).
- Každý upravitelný model má vlastní `.blend` vedle `.glb`.
- Okolí při úpravě modelu dodává dočasný kontext z manifestu, který se do
  zdroje nikdy neuloží.
- Cutscény budou samostatné soubory (`cutscene_01.blend` → `.glb` s akcemi),
  ne vlastnost layoutu.

---

## Co zbývá

- Terrain reference: `Terrain3D ▸ Bake ArrayMesh` → decimovaný mesh jako
  zamčená podlaha v Blenderu i v kontextu (dnes je terén jen krabice).
- Volitelně MultiMesh a live-link transformací přes socket.
