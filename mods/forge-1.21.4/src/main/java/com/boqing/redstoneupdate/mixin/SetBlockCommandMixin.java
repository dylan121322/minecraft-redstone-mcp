package com.boqing.redstoneupdate.mixin;

import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.arguments.blocks.BlockInput;
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
import java.util.function.Predicate;

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
        CommandSourceStack source,
        BlockPos pos,
        BlockInput block,
        SetBlockCommand.Mode mode,
        Predicate<CommandSourceStack> predicate,
        CallbackInfoReturnable<Integer> cir
    ) {
        if (cir.getReturnValue() != 1) return;
        if (pos == null || block == null) return;

        try {
            BlockState state = block.getState();
            Block blockType = state.getBlock();
            ServerLevel level = source.getLevel();

            if (!POWER_CONSUMERS.contains(blockType)) return;

            // Tell the placed block that each neighbor changed, so redstone
            // components (lamps, dust, torches) detect existing power sources.
            for (Direction dir : Direction.values()) {
                BlockPos neighborPos = pos.relative(dir);
                BlockState neighborState = level.getBlockState(neighborPos);
                level.neighborChanged(pos, neighborState.getBlock(), null);
            }

            // Notify neighbors about this block, and refresh rendering.
            level.updateNeighborsAt(pos, blockType);
            level.sendBlockUpdated(pos, state, state, Block.UPDATE_ALL);

            // Diode blocks (repeater/comparator) decide their powered state via
            // checkTickOnNeighbor, which /setblock never calls. Invoke it directly
            // so the diode schedules its own tick and updates POWERED correctly.
            if (blockType instanceof DiodeBlock) {
                ((DiodeBlockInvoker) blockType).invokeCheckTickOnNeighbor(level, pos, level.getBlockState(pos));
            }
        } catch (Exception ignored) {
        }
    }
}
