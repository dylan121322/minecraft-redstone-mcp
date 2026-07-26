// 8-bit ALU: ADD, SUB, AND, OR, XOR, NOT, JUMP
// From ujjwal-2001/RISCV_8bit_pipeline ALU.v
module ALU(input [7:0] data1, input [7:0] data2, input [3:0] ALU_control,
           output reg [7:0] ALU_result, output wire zero);
    parameter AND=0, OR=1, ADD=2, XOR=3, NOT=4, SUB=6, JUMP=12;
    assign zero = (ALU_result == 0);
    always @* begin
        case(ALU_control)
            AND: ALU_result = data1 & data2;
            OR:  ALU_result = data1 | data2;
            ADD: ALU_result = data1 + data2;
            SUB: ALU_result = data1 - data2;
            XOR: ALU_result = data1 ^ data2;
            NOT: ALU_result = ~data1;
            JUMP:ALU_result = 0;
            default: ALU_result = 0;
        endcase
    end
endmodule
