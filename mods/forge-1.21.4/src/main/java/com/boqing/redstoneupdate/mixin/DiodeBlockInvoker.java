package com.boqing.redstoneupdate.mixin;

import net.minecraft.core.BlockPos;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.DiodeBlock;
import net.minecraft.world.level.block.state.BlockState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Invoker;

/**
 * Exposes DiodeBlock's protected checkTickOnNeighbor so we can force
 * repeaters/comparators to re-evaluate their input after /setblock.
 */
@Mixin(DiodeBlock.class)
public interface DiodeBlockInvoker {
    @Invoker("checkTickOnNeighbor")
    void invokeCheckTickOnNeighbor(Level level, BlockPos pos, BlockState state);
}
