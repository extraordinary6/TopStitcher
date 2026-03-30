module param_adder #(
    parameter WIDTH = 8,
    parameter DEPTH = 4
)(
    input wire                clk,
    input wire                rst_n,
    input wire [WIDTH-1:0]    a,
    input wire [WIDTH-1:0]    b,
    output wire [WIDTH-1:0]   sum
);

    assign sum = a + b;

endmodule
