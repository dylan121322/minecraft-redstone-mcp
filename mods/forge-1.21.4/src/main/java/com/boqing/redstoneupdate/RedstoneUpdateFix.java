package com.boqing.redstoneupdate;

import net.minecraftforge.fml.common.Mod;

/**
 * Entry point for the Redstone Update Fix mod.
 * Patches /setblock to trigger redstone neighbor updates (fixes MC-31100).
 */
@Mod("redstone_update_fix")
public class RedstoneUpdateFix {
    public RedstoneUpdateFix() {
        // Mixin does all the work. This class exists only to satisfy
        // Forge's javafml requirement that every modId in mods.toml
        // has a corresponding @Mod-annotated class.
    }
}
