// RISC-V 8-bit ALU Control — alu_op + funct → alu_control
// From ujjwal-2001/RISCV_8bit_pipeline ALU_Control.v
module ALU_Control(
    input wire [1:0] alu_op,
    input wire [9:0] funct,
    output reg [3:0] alu_control
);
    parameter AND  = 4'b0000;
    parameter OR   = 4'b0001;
    parameter ADD  = 4'b0010;
    parameter XOR  = 4'b0011;
    parameter NOT  = 4'b0100;
    parameter SUB  = 4'b0110;
    parameter JUMP = 4'b1100;

    always @* begin
        casex(alu_op)
            2'b00: alu_control = ADD;
            2'b01: alu_control = SUB;
            2'b10: casex(funct)
                10'b0000000000: alu_control = ADD;
                10'b0100000000: alu_control = SUB;
                10'b0000000111: alu_control = AND;
                10'b0000000110: alu_control = OR;
                10'b0000000100: alu_control = XOR;
                10'b0000000011: alu_control = XOR;
                10'b0000000100: alu_control = NOT;
                default: alu_control = AND;
            endcase
            2'b11: alu_control = JUMP;
            default: alu_control = AND;
        endcase
    end
endmodule
