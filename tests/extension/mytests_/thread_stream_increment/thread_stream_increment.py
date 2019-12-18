from __future__ import absolute_import
from __future__ import print_function
import sys
import os
import numpy as np

# the next line can be removed after installation
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from veriloggen import *
import veriloggen.thread as vthread
import veriloggen.types.axi as axi

def mkLed():
    m = Module('blinkled')
    clk = m.Input('CLK')
    rst = m.Input('RST')
    
    datawidth = 32
    addrwidth = 10
    saxi_length = 4

    ram_src = vthread.RAM(m, 'ram_src', clk, rst, datawidth, addrwidth)
    ram_dst = vthread.RAM(m, 'ram_dst', clk, rst, datawidth, addrwidth)
    myaxi = vthread.AXIM(m, 'myaxi', clk, rst, datawidth)
    saxi = vthread.AXISLiteRegister(m, 'saxi', clk, rst, datawidth=datawidth, length=saxi_length)
    
    strm = vthread.Stream(m, 'strm_increment', clk, rst)
    src = strm.source('src')
    
    dst = src + 1
    strm.sink(dst, 'dst')

    def comp_stream(width, height, offset):
        strm.set_source('src', ram_src, offset, width * height)
        strm.set_sink('dst', ram_dst, offset, width * height)
        strm.run()
        strm.join()

    def comp_sequential(width, height, offset):
        for y in range(height):
            for x in range(width):
                i = x + y * width
                src = ram_src.read(offset + i)
                dst = src + 1
                ram_dst.write(offset + i, dst)

    def check(offset_stream, offset_seq):
        all_ok = True
        st = ram_dst.read(offset_stream)
        sq = ram_dst.read(offset_seq)
        if vthread.verilog.NotEql(st, sq):
            all_ok = False
        if all_ok:
            print('# verify: PASSED')
        else:
            print('# verify: FAILED')

    def comp():
        saxi.wait_flag(0, value=1, resetvalue=0)
        width = saxi.read(2)
        height = saxi.read(3)
        size = width * height

        offset = 0
        myaxi.dma_read(ram_src, offset, 0, size)
        comp_stream(width, height, offset)
        myaxi.dma_write(ram_dst, offset, 1024, size)

        offset = size
        myaxi.dma_read(ram_src, offset, 0, size)
        comp_sequential(width, height, offset)
        myaxi.dma_write(ram_dst, offset, 1024 * 2, size)

        check(0, offset)

        vthread.finish()

    th = vthread.Thread(m, 'th_comp', clk, rst, comp)
    fsm = th.start()

    return m


def mkTest(memimg_name=None):
    m = Module('test')

    # target instance
    led = mkLed()

    # copy paras and ports
    params = m.copy_params(led)
    ports = m.copy_sim_ports(led)

    clk = ports['CLK']
    rst = ports['RST']

    memory = axi.AxiMemoryModel(m, 'memory', clk, rst, memimg_name=memimg_name)
    memory.connect(ports, 'myaxi')
    maxi = vthread.AXIMLite(m, 'maxi', clk, rst, noio=True)
    maxi.connect(ports, 'saxi')

    def ctrl():
        width, height = [8, 6]
        
        awaddr = 2 * 4
        maxi.write(awaddr, width)

        awaddr = 3 * 4
        maxi.write(awaddr, height)

        awaddr = 0 * 4
        maxi.write(awaddr, 1)

        araddr = 1 * 4
        v = maxi.read(araddr)
        while v == 0:
            v = maxi.read(araddr)

    th = vthread.Thread(m, 'th_ctrl', clk, rst, ctrl)
    fsm = th.start()

    uut = m.Instance(led, 'uut',
                     params=m.connect_params(led),
                     ports=m.connect_ports(led))

    #simulation.setup_waveform(m, uut)
    simulation.setup_clock(m, clk, hperiod=5)
    simulation.setup_waveform(m, uut, m.get_vars())
    init = simulation.setup_reset(m, rst, m.make_reset(), period=100)

    init.add(
        Delay(200000),
        Systask('finish'),
    )

    return m


def run(filename='tmp.v', simtype='iverilog', outputfile=None):

    if outputfile is None:
        outputfile = os.path.splitext(os.path.basename(__file__))[0] + '.out'

    memimg_name = 'memimg_' + outputfile

    test = mkTest(memimg_name=memimg_name)

    if filename is not None:
        test.to_verilog(filename)

    sim = simulation.Simulator(test, sim=simtype)
    rslt = sim.run(outputfile=outputfile)
    lines = rslt.splitlines()
    if simtype == 'verilator' and lines[-1].startswith('-'):
        rslt = '\n'.join(lines[:-1])

    # sim.view_waveform()
    
    return rslt


if __name__ == '__main__':
    rslt = run(filename='tmp.v')
    print(rslt)
