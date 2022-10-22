from caches import cached_test
from event_testing.results import TestResult
from event_testing.test_base import BaseTest
from event_testing.test_events import TestEvent
from interactions import ParticipantTypeSingle
from routing.walkstyle.walkstyle_tuning import TunableWalkstyle
from sims4.tuning.tunable import HasTunableSingletonFactory, AutoFactoryInit, TunableEnumEntry, TunableList


class WalkstyleTest(HasTunableSingletonFactory, AutoFactoryInit, BaseTest):
    test_events = (TestEvent.InteractionStart,)
    FACTORY_TUNABLES = {
        'subject': TunableEnumEntry(
            description='The subject of the test.',
            tunable_type=ParticipantTypeSingle,
            default=ParticipantTypeSingle.Actor
        ),
        'prohibited_walkstyles': TunableList(tunable=TunableWalkstyle(pack_safe=True))
    }

    __slots__ = ('subject', 'prohibited_walkstyles',)

    def get_expected_args(self):
        return {'subjects': self.subject}

    @cached_test
    def __call__(self, subjects=(), **kwargs):
        subject = next(iter(subjects))
        if subject is not None and subject.is_sim:
            sim = subject.get_sim_instance()
            current_path = sim.routing_component.current_path
            if current_path is not None:
                for node in current_path.nodes:
                    if node.walkstyle in self.prohibited_walkstyles:
                        return TestResult(False, "Prohibited walkstyle")

        return TestResult.TRUE