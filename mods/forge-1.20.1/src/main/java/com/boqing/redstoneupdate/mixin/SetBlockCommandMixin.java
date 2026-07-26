package com.boqing.redstoneupdate.mixin;

import com.mojang.brigadier.context.CommandContext;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.commands.SetBlockCommand;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.DiodeBlock;
import net.minecraft.world.level.block.state.BlockState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

import java.util.Set;

/**
 * Patches /setblock to trigger redstone updates (MC-31100) for 1.20.1.
 *
 * 1.20.1 setBlock signature: (CommandContext, BlockPos, BlockState, int)
 * No BlockInput, no Mode enum, no Orientation.
 * neighborChanged uses BlockPos instead of Orientation.
 */
@Mixin(SetBlockCommand.class)
public class SetBlockCommandMixin {

    private static final Set<Block> POWER_CONSUMERS = Set.of(
        Blocks.REPEATER,
        Blocks.COMPARATOR,
        Blocks.REDSTONE_WIRE,
        Blocks.REDSTONE_LAMP,
        Blocks.OBSERVER,
        Blocks.REDSTONE_TORCH,
        Blocks.REDSTONE_WALL_TORCH
    );

    @Inject(method = "setBlock", at = @At("RETURN"))
    private static void afterSetBlock(
        CommandContext<CommandSourceStack> ctx,
        BlockPos pos,
        BlockState state,
        int mode,
        CallbackInfoReturnable<Integer> cir
    ) {
        if (cir.getReturnValue() != 1) return;
        if (pos == null || state == null) return;

        try {
            Block blockType = state.getBlock();
            ServerLevel level = ctx.getSource().getLevel();

            if (!POWER_CONSUMERS.contains(blockType)) return;

            // Tell the placed block about each neighbor (1.20.1: BlockPos, no Orientation)
            for (Direction dir : Direction.values()) {
                BlockPos neighborPos = pos.relative(dir);
                BlockState neighborState = level.getBlockState(neighborPos);
                level.neighborChanged(pos, neighborState.getBlock(), neighborPos);
            }

            // Notify neighbors about this block
            level.updateNeighborsAt(pos, blockType);
            level.sendBlockUpdated(pos, state, state, Block.UPDATE_ALL);

            // Diode blocks need checkTickOnNeighbor to schedule their own tick
            if (blockType instanceof DiodeBlock) {
                ((DiodeBlockInvoker) blockType).invokeCheckTickOnNeighbor(level, pos, level.getBlockState(pos));
            }
        } catch (Exception ignored) {
        }
    }
}
