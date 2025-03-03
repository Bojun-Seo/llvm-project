"""Test stepping over watchpoints."""



import lldb
from lldbsuite.test.decorators import *
from lldbsuite.test.lldbtest import *
from lldbsuite.test import lldbutil


class TestStepOverWatchpoint(TestBase):
    NO_DEBUG_INFO_TESTCASE = True

    def get_to_start(self, bkpt_text):
        """Test stepping over watchpoints."""
        self.build()
        target, process, thread, bkpt = lldbutil.run_to_source_breakpoint(self, bkpt_text,
                                                                       lldb.SBFileSpec("main.c"))
        frame = thread.GetFrameAtIndex(0)
        self.assertTrue(frame.IsValid(), "Failed to get frame.")

        read_value = frame.FindValue('g_watch_me_read',
                                     lldb.eValueTypeVariableGlobal)
        self.assertTrue(read_value.IsValid(), "Failed to find read value.")

        error = lldb.SBError()

        # resolve_location=True, read=True, write=False
        read_watchpoint = read_value.Watch(True, True, False, error)
        self.assertSuccess(error, "Error while setting watchpoint")
        self.assertTrue(read_watchpoint, "Failed to set read watchpoint.")

        # Disable the breakpoint we hit so we don't muddy the waters with
        # stepping off from the breakpoint:
        bkpt.SetEnabled(False)
        
        return (target, process, thread, read_watchpoint)
    
    # Read-write watchpoints not supported on SystemZ
    @expectedFailureAll(archs=['s390x'])
    @add_test_categories(["basic_process"])
    def test_step_over(self):
        target, process, thread, wp = self.get_to_start("Set a breakpoint here")
    
        thread.StepOver()
        self.assertStopReason(thread.GetStopReason(), lldb.eStopReasonWatchpoint,
                        STOPPED_DUE_TO_WATCHPOINT)
        self.assertEquals(thread.GetStopDescription(20), 'watchpoint 1')

    @expectedFailureAll(
        oslist=["freebsd", "linux"],
        archs=[
            'aarch64',
            'arm'],
        bugnumber="llvm.org/pr26031")
    # Read-write watchpoints not supported on SystemZ
    @expectedFailureAll(archs=['s390x'])
    @expectedFailureAll(
        oslist=["ios", "watchos", "tvos", "bridgeos", "macosx"],
        archs=['aarch64', 'arm'],
        bugnumber="<rdar://problem/34027183>")
    @add_test_categories(["basic_process"])
    def test_step_instruction(self):
        target, process, thread, wp = self.get_to_start("Set breakpoint after call")

        self.step_inst_for_watchpoint(1)

        write_value = frame.FindValue('g_watch_me_write',
                                      lldb.eValueTypeVariableGlobal)
        self.assertTrue(write_value, "Failed to find write value.")

        # Most of the MIPS boards provide only one H/W watchpoints, and S/W
        # watchpoints are not supported yet
        arch = self.getArchitecture()
        if re.match("^mips", arch) or re.match("powerpc64le", arch):
            self.runCmd("watchpoint delete 1")

        # resolve_location=True, read=False, write=True
        write_watchpoint = write_value.Watch(True, False, True, error)
        self.assertTrue(write_watchpoint, "Failed to set write watchpoint.")
        self.assertSuccess(error, "Error while setting watchpoint")

        thread.StepOver()
        self.assertStopReason(thread.GetStopReason(), lldb.eStopReasonWatchpoint,
                        STOPPED_DUE_TO_WATCHPOINT)
        self.assertEquals(thread.GetStopDescription(20), 'watchpoint 2')

        process.Continue()
        self.assertState(process.GetState(), lldb.eStateStopped,
                         PROCESS_STOPPED)
        self.assertEquals(thread.GetStopDescription(20), 'step over')

        self.step_inst_for_watchpoint(2)

    def step_inst_for_watchpoint(self, wp_id):
        watchpoint_hit = False
        current_line = self.frame().GetLineEntry().GetLine()
        while self.frame().GetLineEntry().GetLine() == current_line:
            self.thread().StepInstruction(False)  # step_over=False
            stop_reason = self.thread().GetStopReason()
            if stop_reason == lldb.eStopReasonWatchpoint:
                self.assertFalse(watchpoint_hit, "Watchpoint already hit.")
                expected_stop_desc = "watchpoint %d" % wp_id
                actual_stop_desc = self.thread().GetStopDescription(20)
                self.assertEquals(actual_stop_desc, expected_stop_desc,
                                "Watchpoint ID didn't match.")
                watchpoint_hit = True
            else:
                self.assertStopReason(stop_reason, lldb.eStopReasonPlanComplete,
                                STOPPED_DUE_TO_STEP_IN)
        self.assertTrue(watchpoint_hit, "Watchpoint never hit.")
