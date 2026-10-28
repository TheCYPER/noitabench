# Knowledge base (the answer key for the notes)

Generated from `content/*.json` by `python -m noitabench knowledge --doc docs/knowledge-base.md`; please do not edit by hand.
When a run is scored, the agent's notes are turned into claims of a fixed form, and each claim is checked against the facts below: a match is one note that is right.

- [told]: the game already told the player this (a potion's name states its effect, a spell card shows its type and uses). Writing it down counts for the accuracy of the notes, not for "learned something new".
- (scenes: ...): this fact is what that encounter asks about.
- The code at the end of a line is the id of the fact.

## 1. Different for every rule seed: the secret recipes

In every rule seed, each of the 8 secret potions (Lively Concoction, Invulnerability Potion, Mana Surge Potion, Critical Potion, Berserk Potion, Levitation Potion, Invisibility Potion and Fireproofing Potion) has one recipe: 3 ingredients drawn from a pool of 12 materials. Put together in one bottle, or poured together, they become the potion.
The recipes differ from seed to seed and are not listed in this document (a human participant must not see them). Researchers print one seed's recipes with `python -m noitabench knowledge --seed N`.

## 2. Knowledge that belongs to this game

This is the game's own content, or what an encounter is there to teach. A player has a chance to learn it only by meeting the matching encounter. (73 facts)

### Reactions (what happens when two things touch) (3)

- acid + things acid corrodes (water, blood, sand, coal, gunpowder, ground, rock, wood, bone dust, fungus powder) -> flammable gas + air (scenes: E07 The chain, E16 Thin acid layer) `reaction:r04`
- steam + solid terrain (ground, rock, wood, brickwork, metal) -> water + the same solid terrain `reaction:r12`
- water-family liquids (water, blood) + something burning -> steam + the fire goes out `reaction:r14`

### What drinking does (12)

- Drinking "Heal Potion": heals you [told] `drink:potion_heal`
- Drinking "Mana Potion": refills the mana of your wand [told] `drink:potion_mana`
- Drinking "Haste Potion": makes you faster for a while [told] `drink:potion_haste`
- Drinking "Lively Concoction": heals you steadily for a while [told] `drink:potion_lively`
- Drinking slime: nothing happens `drink:slime`
- Drinking "Invulnerability Potion": no damage can hurt you for a while [told] `drink:potion_invulnerable`
- Drinking "Mana Surge Potion": your wands regain mana faster for a while [told] `drink:potion_mana_regen`
- Drinking "Critical Potion": raises your chance of a critical hit for a while [told] `drink:potion_crit`
- Drinking "Berserk Potion": doubles the damage of your shots for a while [told] `drink:potion_berserk`
- Drinking "Levitation Potion": flying costs no energy for a while [told] `drink:potion_levitation`
- Drinking "Invisibility Potion": enemies cannot see you for a while; casting or kicking shows you for a moment [told] `drink:potion_invisible`
- Drinking "Fireproofing Potion": you cannot catch fire for a while [told] `drink:potion_fireproof`

### Properties of materials (54)

- Water sinks below slime `property:water:sinks_in:slime`
- Blood sinks below slime `property:blood:sinks_in:slime`
- Oil floats on slime `property:oil:floats_on:slime`
- Whiskey sinks below slime `property:whiskey:sinks_in:slime`
- Acid floats on slime `property:acid:floats_on:slime`
- Lava sinks below slime `property:lava:sinks_in:slime`
- Toxic sludge floats on slime `property:toxic_sludge:floats_on:slime`
- Toxic sludge looks like slime (the colours are close, easy to confuse) (scenes: E24 The old room and the new room) `property:toxic_sludge:looks_like:slime`
- Sand sinks below slime `property:sand:sinks_in:slime`
- Coal sinks below slime `property:coal:sinks_in:slime`
- Gunpowder sinks below slime `property:gunpowder:sinks_in:slime`
- Metal does not burn `property:metal:does_not_burn`
- Metal resists acid `property:metal:resists_acid`
- Metal cannot be broken by the starting digging spell `property:metal:undiggable`
- Gold dust does not burn `property:gold_dust:does_not_burn`
- Gold dust resists acid `property:gold_dust:resists_acid`
- Gold dust sinks below acid `property:gold_dust:sinks_in:acid`
- Gold dust sinks below blood `property:gold_dust:sinks_in:blood`
- Gold dust sinks below lava `property:gold_dust:sinks_in:lava`
- Gold dust sinks below oil `property:gold_dust:sinks_in:oil`
- Gold dust sinks below slime `property:gold_dust:sinks_in:slime`
- Gold dust sinks below toxic sludge `property:gold_dust:sinks_in:toxic_sludge`
- Gold dust sinks below water `property:gold_dust:sinks_in:water`
- Gold dust sinks below whiskey `property:gold_dust:sinks_in:whiskey`
- Bone dust is eaten away by acid `property:bone_dust:corroded_by_acid`
- Bone dust does not burn `property:bone_dust:does_not_burn`
- Bone dust floats on lava `property:bone_dust:floats_on:lava`
- Bone dust sinks below acid `property:bone_dust:sinks_in:acid`
- Bone dust sinks below blood `property:bone_dust:sinks_in:blood`
- Bone dust sinks below oil `property:bone_dust:sinks_in:oil`
- Bone dust sinks below slime `property:bone_dust:sinks_in:slime`
- Bone dust sinks below toxic sludge `property:bone_dust:sinks_in:toxic_sludge`
- Bone dust sinks below water `property:bone_dust:sinks_in:water`
- Bone dust sinks below whiskey `property:bone_dust:sinks_in:whiskey`
- Fungus powder is eaten away by acid `property:fungus_powder:corroded_by_acid`
- Fungus powder does not burn `property:fungus_powder:does_not_burn`
- Fungus powder floats on blood `property:fungus_powder:floats_on:blood`
- Fungus powder floats on lava `property:fungus_powder:floats_on:lava`
- Fungus powder floats on water `property:fungus_powder:floats_on:water`
- Fungus powder sinks below acid `property:fungus_powder:sinks_in:acid`
- Fungus powder sinks below oil `property:fungus_powder:sinks_in:oil`
- Fungus powder sinks below slime `property:fungus_powder:sinks_in:slime`
- Fungus powder sinks below toxic sludge `property:fungus_powder:sinks_in:toxic_sludge`
- Fungus powder sinks below whiskey `property:fungus_powder:sinks_in:whiskey`
- Slime does not burn `property:slime:does_not_burn`
- Slime floats on blood `property:slime:floats_on:blood`
- Slime floats on lava `property:slime:floats_on:lava`
- Slime floats on water `property:slime:floats_on:water`
- Slime floats on whiskey `property:slime:floats_on:whiskey`
- Slime looks like toxic sludge (the colours are close, easy to confuse) `property:slime:looks_like:toxic_sludge`
- Slime resists acid `property:slime:resists_acid`
- Slime sinks below acid `property:slime:sinks_in:acid`
- Slime sinks below oil `property:slime:sinks_in:oil`
- Slime sinks below toxic sludge `property:slime:sinks_in:toxic_sludge`

### Creatures (1)

- Hämis cannot jump out of a water pit deeper than it can jump: once it falls in, it is stuck (scenes: E10 The pool in the way) `creature:longleg:cannot_cross_deep_water`

### What the encounters teach (3)

- Only a bomb together with the Explosive Projectile modifier can blast open the seal's bricks: load both on one wand, the modifier first and the bomb after it (scenes: E06 The sealed deep) `scene:E06:seal_key`
- The flooded room has no other exit; the way out is to dig through the floor under the water: the water drains into the cellar below and you follow it down (scenes: E08 Flooded passage) `scene:E08:flooded_room_exit`
- The bottle nearest the door is always toxic sludge, never the healing potion (scenes: E21 Hurt, and four bottles with no names) `scene:E21:nearest_bottle_to_door`

## 3. Noita common knowledge

Knowledge from the original Noita. Someone who has played it (or a model from memory) may know it already; an encounter that leans on it changes nothing: a correct note is correct, but it is not "something new learned". (209 facts)

### Reactions (what happens when two things touch) (11)

- lava + water -> rock + steam (scenes: E02 Lava river, E04 The laboratory ruin, E05 The vault behind the lava door, E07 The chain, E14 Three unlabelled bottles) `reaction:r01`
- lava + blood -> rock + steam (scenes: E02 Lava river, E04 The laboratory ruin, E05 The vault behind the lava door, E07 The chain, E14 Three unlabelled bottles) `reaction:r02`
- fire + water -> fire + steam `reaction:r03`
- lava + burnable things (oil, whiskey, coal, wood) -> lava + fire `reaction:r05`
- lava + flammable gas -> lava + fire `reaction:r06`
- fire + flammable gas -> fire + fire `reaction:r07`
- lava + sand -> lava + lava `reaction:r08`
- coal + fire -> fire + air `reaction:r09`
- whiskey + fire -> fire + flammable gas `reaction:r10`
- water + toxic sludge -> water + water (scenes: E24 The old room and the new room) `reaction:r11`
- lava + toxic sludge -> rock + flammable gas (scenes: E02 Lava river, E04 The laboratory ruin, E07 The chain, E14 Three unlabelled bottles) `reaction:r13`

### What drinking does (7)

- Drinking water: makes you wet `drink:water`
- Drinking blood: nothing happens `drink:blood`
- Drinking oil: covers you in oil, so that you catch fire easily (scenes: E21 Hurt, and four bottles with no names) `drink:oil`
- Drinking whiskey: makes you drunk, your aim shakes (scenes: E21 Hurt, and four bottles with no names) `drink:whiskey`
- Drinking acid: hurts you `drink:acid`
- Drinking lava: burns you and sets you on fire `drink:lava`
- Drinking toxic sludge: poisons you, a slow loss of health (scenes: E21 Hurt, and four bottles with no names) `drink:toxic_sludge`

### Properties of materials (103)

- Steam does not burn `property:steam:does_not_burn`
- Flammable gas burns `property:flammable_gas:burns`
- Water is eaten away by acid `property:water:corroded_by_acid`
- Water does not burn `property:water:does_not_burn`
- Water floats on blood `property:water:floats_on:blood`
- Water floats on lava `property:water:floats_on:lava`
- Water sinks below acid `property:water:sinks_in:acid`
- Water sinks below oil `property:water:sinks_in:oil`
- Water sinks below toxic sludge `property:water:sinks_in:toxic_sludge`
- Water sinks below whiskey `property:water:sinks_in:whiskey`
- Blood is eaten away by acid `property:blood:corroded_by_acid`
- Blood does not burn `property:blood:does_not_burn`
- Blood floats on lava `property:blood:floats_on:lava`
- Blood looks like lava (the colours are close, easy to confuse) `property:blood:looks_like:lava`
- Blood sinks below acid `property:blood:sinks_in:acid`
- Blood sinks below oil `property:blood:sinks_in:oil`
- Blood sinks below toxic sludge `property:blood:sinks_in:toxic_sludge`
- Blood sinks below water `property:blood:sinks_in:water`
- Blood sinks below whiskey `property:blood:sinks_in:whiskey`
- Oil burns (scenes: E09 The shooter on the wooden perch, E23 The vial and the deep pool) `property:oil:burns`
- Oil floats on acid `property:oil:floats_on:acid`
- Oil floats on blood `property:oil:floats_on:blood`
- Oil floats on lava `property:oil:floats_on:lava`
- Oil floats on toxic sludge `property:oil:floats_on:toxic_sludge`
- Oil floats on water `property:oil:floats_on:water`
- Oil floats on whiskey `property:oil:floats_on:whiskey`
- Oil looks like whiskey (the colours are close, easy to confuse) `property:oil:looks_like:whiskey`
- Oil resists acid `property:oil:resists_acid`
- Whiskey burns (scenes: E23 The vial and the deep pool) `property:whiskey:burns`
- Whiskey floats on blood `property:whiskey:floats_on:blood`
- Whiskey floats on lava `property:whiskey:floats_on:lava`
- Whiskey floats on water `property:whiskey:floats_on:water`
- Whiskey looks like lava (the colours are close, easy to confuse) `property:whiskey:looks_like:lava`
- Whiskey looks like oil (the colours are close, easy to confuse) `property:whiskey:looks_like:oil`
- Whiskey resists acid `property:whiskey:resists_acid`
- Whiskey sinks below acid `property:whiskey:sinks_in:acid`
- Whiskey sinks below oil `property:whiskey:sinks_in:oil`
- Whiskey sinks below toxic sludge `property:whiskey:sinks_in:toxic_sludge`
- Acid does not burn `property:acid:does_not_burn`
- Acid floats on blood `property:acid:floats_on:blood`
- Acid floats on lava `property:acid:floats_on:lava`
- Acid floats on toxic sludge `property:acid:floats_on:toxic_sludge`
- Acid floats on water `property:acid:floats_on:water`
- Acid floats on whiskey `property:acid:floats_on:whiskey`
- Touching acid hurts you (damage, poison or fire) (scenes: E16 Thin acid layer) `property:acid:harms_on_contact`
- Acid looks like toxic sludge (the colours are close, easy to confuse) `property:acid:looks_like:toxic_sludge`
- Acid sinks below oil `property:acid:sinks_in:oil`
- Lava does not burn `property:lava:does_not_burn`
- Touching lava hurts you (damage, poison or fire) `property:lava:harms_on_contact`
- Lava looks like blood (the colours are close, easy to confuse) `property:lava:looks_like:blood`
- Lava looks like whiskey (the colours are close, easy to confuse) `property:lava:looks_like:whiskey`
- Lava resists acid `property:lava:resists_acid`
- Lava sinks below acid `property:lava:sinks_in:acid`
- Lava sinks below blood `property:lava:sinks_in:blood`
- Lava sinks below oil `property:lava:sinks_in:oil`
- Lava sinks below toxic sludge `property:lava:sinks_in:toxic_sludge`
- Lava sinks below water `property:lava:sinks_in:water`
- Lava sinks below whiskey `property:lava:sinks_in:whiskey`
- Toxic sludge does not burn `property:toxic_sludge:does_not_burn`
- Toxic sludge floats on blood `property:toxic_sludge:floats_on:blood`
- Toxic sludge floats on lava `property:toxic_sludge:floats_on:lava`
- Toxic sludge floats on water `property:toxic_sludge:floats_on:water`
- Toxic sludge floats on whiskey `property:toxic_sludge:floats_on:whiskey`
- Touching toxic sludge hurts you (damage, poison or fire) (scenes: E23 The vial and the deep pool, E24 The old room and the new room) `property:toxic_sludge:harms_on_contact`
- Toxic sludge looks like acid (the colours are close, easy to confuse) `property:toxic_sludge:looks_like:acid`
- Toxic sludge resists acid `property:toxic_sludge:resists_acid`
- Toxic sludge sinks below acid `property:toxic_sludge:sinks_in:acid`
- Toxic sludge sinks below oil `property:toxic_sludge:sinks_in:oil`
- Sand is eaten away by acid `property:sand:corroded_by_acid`
- Sand does not burn `property:sand:does_not_burn`
- Sand sinks below acid `property:sand:sinks_in:acid`
- Sand sinks below blood `property:sand:sinks_in:blood`
- Sand sinks below oil `property:sand:sinks_in:oil`
- Sand sinks below toxic sludge `property:sand:sinks_in:toxic_sludge`
- Sand sinks below water `property:sand:sinks_in:water`
- Sand sinks below whiskey `property:sand:sinks_in:whiskey`
- Coal burns `property:coal:burns`
- Coal is eaten away by acid `property:coal:corroded_by_acid`
- Coal sinks below acid `property:coal:sinks_in:acid`
- Coal sinks below blood `property:coal:sinks_in:blood`
- Coal sinks below oil `property:coal:sinks_in:oil`
- Coal sinks below toxic sludge `property:coal:sinks_in:toxic_sludge`
- Coal sinks below water `property:coal:sinks_in:water`
- Coal sinks below whiskey `property:coal:sinks_in:whiskey`
- Gunpowder burns `property:gunpowder:burns`
- Gunpowder is eaten away by acid `property:gunpowder:corroded_by_acid`
- Gunpowder explodes when fire reaches it (scenes: E09 The shooter on the wooden perch, E22 Short way, long way) `property:gunpowder:explodes_when_lit`
- Gunpowder sinks below acid `property:gunpowder:sinks_in:acid`
- Gunpowder sinks below blood `property:gunpowder:sinks_in:blood`
- Gunpowder sinks below lava `property:gunpowder:sinks_in:lava`
- Gunpowder sinks below oil `property:gunpowder:sinks_in:oil`
- Gunpowder sinks below toxic sludge `property:gunpowder:sinks_in:toxic_sludge`
- Gunpowder sinks below water `property:gunpowder:sinks_in:water`
- Gunpowder sinks below whiskey `property:gunpowder:sinks_in:whiskey`
- Ground is eaten away by acid `property:ground:corroded_by_acid`
- Ground does not burn `property:ground:does_not_burn`
- Rock is eaten away by acid `property:rock:corroded_by_acid`
- Rock does not burn `property:rock:does_not_burn`
- Wood burns (scenes: E09 The shooter on the wooden perch) `property:wood:burns`
- Wood is eaten away by acid `property:wood:corroded_by_acid`
- Brickwork does not burn `property:brick:does_not_burn`
- Brickwork resists acid `property:brick:resists_acid`
- Brickwork cannot be broken by the starting digging spell (scenes: E06 The sealed deep) `property:brick:undiggable`

### Creatures (9)

- Hämis catches fire easily `creature:longleg:catches_fire_easily`
- Hämis leaps at you `creature:longleg:leaps_at_you`
- Hämis only fights up close `creature:longleg:melee_only`
- A hit on the head hurts Haulikkohiisi more `creature:shotgunner:headshot_bonus`
- Haulikkohiisi shoots from a distance `creature:shotgunner:shoots`
- Water hurts Stendari (scenes: E03 The guard that fire cannot hurt) `creature:firemage_weak:hurt_by_water`
- Stendari is immune to fire (scenes: E03 The guard that fire cannot hurt) `creature:firemage_weak:immune_to_fire`
- Explosions hurt Stendari less `creature:firemage_weak:resists_explosions`
- Stendari shoots from a distance `creature:firemage_weak:shoots`

### Spells (79)

- "Spark Bolt" is a projectile spell [told] `spell:LIGHT_BULLET:type:projectile`
- "Spark Bolt" can be used without limit [told] `spell:LIGHT_BULLET:unlimited_uses`
- "Magic Arrow" is a projectile spell [told] `spell:BULLET:type:projectile`
- "Magic Arrow" can be used without limit [told] `spell:BULLET:unlimited_uses`
- "Bouncing Burst" makes the shot bounce [told] `spell:RUBBER_BALL:bounces`
- "Bouncing Burst" is a projectile spell [told] `spell:RUBBER_BALL:type:projectile`
- "Bouncing Burst" can be used without limit [told] `spell:RUBBER_BALL:unlimited_uses`
- "Energy Orb" makes a large explosion [told] `spell:SLOW_BULLET:blasts`
- The blast of "Energy Orb" digs out ground [told] `spell:SLOW_BULLET:digs_terrain`
- "Energy Orb" is a projectile spell [told] `spell:SLOW_BULLET:type:projectile`
- "Energy Orb" can be used without limit [told] `spell:SLOW_BULLET:unlimited_uses`
- "Bomb" makes a large explosion [told] `spell:BOMB:blasts`
- The blast of "Bomb" digs out ground [told] `spell:BOMB:digs_terrain`
- "Bomb" can be used only a few times [told] `spell:BOMB:limited_uses`
- "Bomb" is a projectile spell [told] `spell:BOMB:type:projectile`
- "Fireball" makes a large explosion [told] `spell:FIREBALL:blasts`
- The blast of "Fireball" digs out ground [told] `spell:FIREBALL:digs_terrain`
- "Fireball" sets things on fire (scenes: E22 Short way, long way) `spell:FIREBALL:ignites`
- "Fireball" can be used only a few times [told] `spell:FIREBALL:limited_uses`
- "Fireball" is a projectile spell [told] `spell:FIREBALL:type:projectile`
- The blast of "Digging Bolt" digs out ground [told] `spell:DIGGER:digs_terrain`
- "Digging Bolt" is a projectile spell [told] `spell:DIGGER:type:projectile`
- "Digging Bolt" can be used without limit [told] `spell:DIGGER:unlimited_uses`
- "Explosion" makes a large explosion [told] `spell:EXPLOSION:blasts`
- The blast of "Explosion" digs out ground [told] `spell:EXPLOSION:digs_terrain`
- "Explosion" is a spell that acts on the spot [told] `spell:EXPLOSION:type:static_projectile`
- "Explosion" can be used without limit [told] `spell:EXPLOSION:unlimited_uses`
- What "Water" hits gets wet [told] `spell:MATERIAL_WATER:makes_wet`
- "Water" sprays water [told] `spell:MATERIAL_WATER:sprays:water`
- "Water" is a spell that sprays a material [told] `spell:MATERIAL_WATER:type:material`
- "Water" can be used without limit [told] `spell:MATERIAL_WATER:unlimited_uses`
- What "Oil" hits gets covered in oil [told] `spell:MATERIAL_OIL:makes_oiled`
- "Oil" sprays oil [told] `spell:MATERIAL_OIL:sprays:oil`
- "Oil" is a spell that sprays a material [told] `spell:MATERIAL_OIL:type:material`
- "Oil" can be used without limit [told] `spell:MATERIAL_OIL:unlimited_uses`
- "Acid" sprays acid [told] `spell:MATERIAL_ACID:sprays:acid`
- "Acid" is a spell that sprays a material [told] `spell:MATERIAL_ACID:type:material`
- "Acid" can be used without limit [told] `spell:MATERIAL_ACID:unlimited_uses`
- "Spark Bolt With Trigger" fires the next spell when it hits something [told] `spell:LIGHT_BULLET_TRIGGER:triggers_on_hit`
- "Spark Bolt With Trigger" is a projectile spell [told] `spell:LIGHT_BULLET_TRIGGER:type:projectile`
- "Spark Bolt With Trigger" can be used without limit [told] `spell:LIGHT_BULLET_TRIGGER:unlimited_uses`
- "Spark Bolt With Timer" fires the next spell after a short time [told] `spell:LIGHT_BULLET_TIMER:triggers_on_timer`
- "Spark Bolt With Timer" is a projectile spell [told] `spell:LIGHT_BULLET_TIMER:type:projectile`
- "Spark Bolt With Timer" can be used without limit [told] `spell:LIGHT_BULLET_TIMER:unlimited_uses`
- "Double Spell" is a multicast that casts several spells at once [told] `spell:BURST_2:type:multicast`
- "Double Spell" can be used without limit [told] `spell:BURST_2:unlimited_uses`
- "Triple Spell" is a multicast that casts several spells at once [told] `spell:BURST_3:type:multicast`
- "Triple Spell" can be used without limit [told] `spell:BURST_3:unlimited_uses`
- "Speed Up" makes the shot fly faster [told] `spell:SPEED:speeds_up`
- "Speed Up" is a modifier that changes the spells after it [told] `spell:SPEED:type:modifier`
- "Speed Up" can be used without limit [told] `spell:SPEED:unlimited_uses`
- "Damage Plus" is a modifier that changes the spells after it [told] `spell:DAMAGE:type:modifier`
- "Damage Plus" can be used without limit [told] `spell:DAMAGE:unlimited_uses`
- "Heavy Shot" makes the shot fly slower [told] `spell:HEAVY_SHOT:slows_shot`
- "Heavy Shot" is a modifier that changes the spells after it [told] `spell:HEAVY_SHOT:type:modifier`
- "Heavy Shot" can be used without limit [told] `spell:HEAVY_SHOT:unlimited_uses`
- "Reduce Spread" is a modifier that changes the spells after it [told] `spell:SPREAD_REDUCE:type:modifier`
- "Reduce Spread" can be used without limit [told] `spell:SPREAD_REDUCE:unlimited_uses`
- "Bounce" makes the shot bounce [told] `spell:BOUNCE:bounces`
- "Bounce" is a modifier that changes the spells after it [told] `spell:BOUNCE:type:modifier`
- "Bounce" can be used without limit [told] `spell:BOUNCE:unlimited_uses`
- "Explosive Projectile" makes the explosion bigger [told] `spell:EXPLOSIVE_PROJECTILE:enlarges_blast`
- "Explosive Projectile" lets the blast break harder materials `spell:EXPLOSIVE_PROJECTILE:raises_blast_durability`
- "Explosive Projectile" makes the shot fly slower [told] `spell:EXPLOSIVE_PROJECTILE:slows_shot`
- "Explosive Projectile" is a modifier that changes the spells after it [told] `spell:EXPLOSIVE_PROJECTILE:type:modifier`
- "Explosive Projectile" can be used without limit [told] `spell:EXPLOSIVE_PROJECTILE:unlimited_uses`
- "Fire Trail" sets things on fire [told] `spell:FIRE_TRAIL:ignites`
- "Fire Trail" leaves fire along its path [told] `spell:FIRE_TRAIL:leaves_trail:fire`
- "Fire Trail" is a modifier that changes the spells after it [told] `spell:FIRE_TRAIL:type:modifier`
- "Fire Trail" can be used without limit [told] `spell:FIRE_TRAIL:unlimited_uses`
- "Water Trail" leaves water along its path [told] `spell:WATER_TRAIL:leaves_trail:water`
- What "Water Trail" hits gets wet [told] `spell:WATER_TRAIL:makes_wet`
- "Water Trail" is a modifier that changes the spells after it [told] `spell:WATER_TRAIL:type:modifier`
- "Water Trail" can be used without limit [told] `spell:WATER_TRAIL:unlimited_uses`
- "Reduce Recharge Time" is a modifier that changes the spells after it [told] `spell:RECHARGE:type:modifier`
- "Reduce Recharge Time" can be used without limit [told] `spell:RECHARGE:unlimited_uses`
- Using "Add Mana" gives the wand mana [told] `spell:MANA_REDUCE:adds_mana`
- "Add Mana" is a modifier that changes the spells after it [told] `spell:MANA_REDUCE:type:modifier`
- "Add Mana" can be used without limit [told] `spell:MANA_REDUCE:unlimited_uses`
