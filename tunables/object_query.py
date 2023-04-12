import services
import random
import sims4.random
from build_buy import get_room_id
from event_testing.tests import TunableTestSet
from event_testing.resolver import SingleObjectResolver, DoubleObjectResolver, SingleSimResolver
from interactions import ParticipantType, ParticipantTypeSingle
from objects import ALL_HIDDEN_REASONS
from objects.components.types import INVENTORY_COMPONENT
from sims.sim_info import SimInfo
from sims4.resources import Types
from sims4.tuning.tunable import HasTunableSingletonFactory, AutoFactoryInit, TunableInterval, Tunable, TunableVariant, TunableEnumSet, TunableEnumEntry, TunableReference
from tag import Tag


class ObjectFilterRandomSingleChoice(HasTunableSingletonFactory, AutoFactoryInit):

    def filter_objects_gen(self, obj_list=()):
        _obj_list = list(obj_list)
        if len(_obj_list) == 0:
            yield from []
        else:
            yield random.choice(_obj_list)


class ObjectFilterRandomMultipleChoice(HasTunableSingletonFactory, AutoFactoryInit):

    FACTORY_TUNABLES = {
        'limit': TunableInterval(tunable_type=int, default_lower=1, default_upper=1, minimum=0)
    }

    __slots__ = ('limit',)

    def filter_objects_gen(self, obj_list=()):
        _obj_list = list(obj_list)
        if len(_obj_list) == 0:
            yield from []
        else:
            num_choices = random.randint(min(len(_obj_list), self.limit.lower_bound), min(len(_obj_list), self.limit.upper_bound))
            yield from random.sample(_obj_list, num_choices)


class ObjectFilterAmountPerRoom(HasTunableSingletonFactory, AutoFactoryInit):

    FACTORY_TUNABLES = {
        'include_outdoors': Tunable(tunable_type=bool, default=True),
        'limit': TunableInterval(tunable_type=int, default_lower=1, default_upper=1, minimum=0)
    }

    __slots__ = ('limit', 'include_outdoors',)

    def filter_objects_gen(self, obj_list=()):
        objs_by_room = {}
        zone_id = services.current_zone_id()
        for obj in obj_list:
            room_id = get_room_id(zone_id, obj.position, obj.level)
            if not self.include_outdoors and room_id == 0:
                continue
            if room_id not in objs_by_room:
                objs_by_room[room_id] = set()
            objs_by_room[room_id].add(obj)

        for room_id, objs in objs_by_room.items():
            num_choices = random.randint(min(len(objs), self.limit.lower_bound), min(len(objs), self.limit.upper_bound))
            yield from random.sample(objs, num_choices)


class ObjectFilterFirst(HasTunableSingletonFactory, AutoFactoryInit):
    def filter_objects_gen(self, obj_list=()):
        for obj in obj_list:
            yield obj
            break


class ObjectFilterLast(HasTunableSingletonFactory, AutoFactoryInit):
    def filter_objects_gen(self, obj_list=()):
        for obj in reversed(list(obj_list)):
            yield obj
            break


class ObjectFilterVariant(TunableVariant):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, first=ObjectFilterFirst.TunableFactory(), last=ObjectFilterLast.TunableFactory(), random_single_choice=ObjectFilterRandomSingleChoice.TunableFactory(), random_multiple_choice=ObjectFilterRandomMultipleChoice.TunableFactory(), amount_per_room=ObjectFilterAmountPerRoom.TunableFactory(), **kwargs)


class BaseObjectSort(HasTunableSingletonFactory, AutoFactoryInit):
    FACTORY_TUNABLES = {
        'distance_actor': TunableEnumEntry(tunable_type=ParticipantTypeSingle, default=ParticipantTypeSingle.Actor),
    }

    def get_participant_position(self, participant):
        if isinstance(participant, SimInfo):
            sim = participant.get_sim_instance()
            if sim is not None:
                return sim.position
        else:
            return participant.position

    def get_participant_level(self, participant):
        if isinstance(participant, SimInfo):
            sim = participant.get_sim_instance()
            if sim is not None:
                return sim.level
        else:
            return participant.level

    def _sort_objects_gen(self, obj_list=(), resolver=None, reverse=False):
        if resolver is None:
            yield from obj_list
        else:
            actor = resolver.get_participant(self.distance_actor)
            relative_position = self.get_participant_position(actor)
            relative_level = self.get_participant_level(actor)
            obj_distance_pairs = list()
            for obj in obj_list:
                delta = obj.position - relative_position
                base_weight = delta.magnitude()
                # score objects on different levels as further away
                if obj.level != relative_level:
                    base_weight *= 2

                obj_distance_pairs.append((base_weight, obj))

            obj_distance_pairs.sort(key=lambda k: k[0], reverse=reverse)
            yield from [k[1] for k in obj_distance_pairs]


class ObjectSortClosest(BaseObjectSort):
    def sort_objects_gen(self, obj_list=(), resolver=None):
        yield from self._sort_objects_gen(obj_list=obj_list, resolver=resolver, reverse=False)


class ObjectSortFarthest(BaseObjectSort):
    def sort_objects_gen(self, obj_list=(), resolver=None):
        yield from self._sort_objects_gen(obj_list=obj_list, resolver=resolver, reverse=True)


class ObjectSortVariant(TunableVariant):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, closest=ObjectSortClosest.TunableFactory(), farthest=ObjectSortFarthest.TunableFactory(), **kwargs)


class _GetObjectsBase(HasTunableSingletonFactory, AutoFactoryInit):
    FACTORY_TUNABLES = {
        'additional_tests': TunableTestSet(),
        'additional_tests_actor': TunableEnumEntry(tunable_type=ParticipantTypeSingle, default=ParticipantTypeSingle.Object),
        'exclude_tags': TunableEnumSet(Tag, enum_default=Tag.INVALID, invalid_enums=(Tag.INVALID,)),
        'filter': ObjectFilterVariant(),
        'sort': ObjectSortVariant(),
    }

    __slots__ = ('additional_tests', 'additional_tests_actor', 'exclude_tags', 'filter', 'sort',)

    def get_test_resolver(self, original_resolver, target):
        if original_resolver is None:
            return SingleObjectResolver(target)
        # get original loot subject as actor
        if isinstance(original_resolver, SingleSimResolver) and self.additional_tests_actor in (ParticipantTypeSingle.Object, ParticipantTypeSingle.TargetSim):
            subject = original_resolver.get_participant(ParticipantTypeSingle.Actor)
        else:
            subject = original_resolver.get_participant(self.additional_tests_actor)

        return DoubleObjectResolver(subject, target)

    def run_additional_tests(self, original_resolver, target):
        resolver = self.get_test_resolver(original_resolver, target)
        return self.additional_tests.run_tests(resolver)

    def _get_filtered_objects_gen(self, obj_list):
        if self.filter is not None:
            yield from self.filter.filter_objects_gen(obj_list)
        else:
            yield from obj_list

    def _get_sorted_objects_gen(self, obj_list, resolver=None):
        if self.sort is not None:
            yield from self.sort.sort_objects_gen(obj_list, resolver=resolver)
        else:
            yield from obj_list

    def _get_objects_gen(self, resolver=None):
        yield from []

    def _get_tested_objects_gen(self, obj_list, resolver):
        if resolver is None:
            yield from obj_list
        else:
            for obj in obj_list:
                if self.run_additional_tests(resolver, obj):
                    yield obj

    def _filter_exclude_tags_gen(self, obj_list):
        for obj in obj_list:
            if self.exclude_tags is not None and obj.has_any_tag(self.exclude_tags):
                continue
            yield obj

    def get_objects_gen(self, resolver=None):
        all_objects = self._get_objects_gen(resolver)
        tag_filtered_objects = self._filter_exclude_tags_gen(all_objects)
        tested_objects = self._get_tested_objects_gen(tag_filtered_objects, resolver)
        sorted_objects = self._get_sorted_objects_gen(tested_objects, resolver=resolver)
        filtered_objects = self._get_filtered_objects_gen(sorted_objects)
        yield from filtered_objects

    def get_closest_object(self, relative_position, relative_level, resolver=None):
        object_list = list(self.get_objects_gen(resolver=resolver))
        weights = []
        for obj in object_list:
            delta = obj.position - relative_position
            base_weight = delta.magnitude()
            # score objects on different levels as further away
            if obj.level != relative_level:
                base_weight *= 2

            # weight = 10/base_weight
            # if obj.parts:
            #     for part in obj.parts:
            #         weights.append((weight, part))
            # else:
            weights.append((base_weight, obj))
        return sims4.random.weighted_random_item(weights)


class GetObjectsFromInventory(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'subject': TunableEnumEntry(tunable_type=ParticipantType, default=ParticipantType.Actor),
        'hidden': Tunable(tunable_type=bool, default=False)
    }

    __slots__ = ('subject', 'hidden',)

    def get_inventory(self, resolver):
        if resolver is not None:
            subject = resolver.get_participant(self.subject)
            return subject.get_sim_instance().get_component(INVENTORY_COMPONENT)

    def _get_objects_gen(self, resolver=None):
        inventory = self.get_inventory(resolver)
        if inventory is not None:
            for obj in inventory:
                if (self.hidden and not inventory.is_object_hidden(obj)) or (not self.hidden and inventory.is_object_hidden(obj)):
                    continue
                yield obj


class GetSituationTargetObject(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'subject': TunableEnumEntry(tunable_type=ParticipantType, default=ParticipantType.Actor),
        'situation': TunableReference(manager=services.get_instance_manager(Types.SITUATION)),
    }

    __slots__ = ('subject', 'situation')

    def get_objects_gen(self, resolver=None):
        situation_manager = services.get_zone_situation_manager()
        if resolver is not None:
            sim_info = resolver.get_participant(self.subject)
            if sim_info and sim_info.is_sim:
                sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                for situation in situation_manager.get_situations_sim_is_in(sim):
                    if situation.guid64 == self.situation.guid64:
                        if hasattr(situation, 'get_target_object'):
                            yield situation.get_target_object()


class GetObjectsOnActiveLot(_GetObjectsBase):

    FACTORY_TUNABLES = {
        'allow_sims': Tunable(tunable_type=bool, default=False)
    }

    __slots__ = ('allow_sims',)

    def _get_objects_gen(self, resolver=None):
        for obj in services.object_manager().valid_objects():
            if obj.is_on_active_lot() and (not obj.is_sim or (obj.is_sim and self.allow_sims)):
                yield obj


class GetAllObjects(_GetObjectsBase):

    FACTORY_TUNABLES = {
        'allow_sims': Tunable(tunable_type=bool, default=False),
    }

    __slots__ = ('allow_sims',)

    def _get_objects_gen(self, resolver=None):
        for obj in services.object_manager().valid_objects():
            if not obj.is_sim or (obj.is_sim and self.allow_sims):
                yield obj


class GetObjectsByTags(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'tags': TunableEnumSet(Tag, enum_default=Tag.INVALID, invalid_enums=(Tag.INVALID,)),
    }

    __slots__ = ('tags', 'exclude_tags')

    def _get_objects_gen(self, resolver=None):
        for obj in services.object_manager().get_objects_with_tags_gen(*self.tags):
            yield obj


class GetObjectsByTuning(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'tuning_id': Tunable(tunable_type=int, default=0),
    }

    __slots__ = ('tuning_id',)

    def _get_objects_gen(self, resolver=None):
        for obj in services.object_manager().valid_objects():
            if hasattr(obj, 'guid64') and obj.guid64 == self.tuning_id:
                yield obj


class GetObjectsByDefinition(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'definition_id': Tunable(tunable_type=int, default=0),
    }

    __slots__ = ('definition_id',)

    def _get_objects_gen(self, resolver=None):
        for obj in services.object_manager().valid_objects():
            if hasattr(obj, 'definition') and obj.definition.id == self.definition_id:
                yield obj


class GetObjectsByAffordance(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'affordance': TunableReference(manager=services.get_instance_manager(Types.INTERACTION)),
    }

    __slots__ = ('affordance',)

    def _get_objects_gen(self, resolver=None):
        for obj in services.object_manager().valid_objects():
            if obj._super_affordances is not None and self.affordance in obj._super_affordances:
                yield obj


class GetObjectsByParticipant(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'participant': TunableEnumEntry(tunable_type=ParticipantType, default=ParticipantType.Object),
    }

    __slots__ = ('participant',)

    def _get_objects_gen(self, resolver=None):
        if resolver is not None:
            for subject in resolver.get_participants(self.participant):
                if isinstance(subject, SimInfo):
                    sim = subject.get_sim_instance()
                    if sim is not None:
                        yield sim
                else:
                    yield subject


class GetObjectsBySimInfo(_GetObjectsBase):
    FACTORY_TUNABLES = {
        'allow_babies': Tunable(tunable_type=bool, default=False),
        'allow_hidden': Tunable(tunable_type=bool, default=False),
    }

    __slots__ = ('allow_babies', 'allow_hidden',)

    def _get_objects_gen(self, resolver=None):
        for sim_info in services.sim_info_manager().get_all():
            if sim_info.is_baby and not self.allow_babies:
                continue
            allow_hidden_flags = ALL_HIDDEN_REASONS if self.allow_hidden else 0
            sim = services.object_manager().get(sim_info.id) if sim_info.is_baby else sim_info.get_sim_instance(allow_hidden_flags=allow_hidden_flags)
            if sim is not None:
                yield sim


class GetObjectsByActiveHousehold(GetObjectsBySimInfo):

    def _get_objects_gen(self, resolver=None):
        for sim_info in services.active_household():
            if sim_info.is_baby and not self.allow_babies:
                continue
            allow_hidden_flags = ALL_HIDDEN_REASONS if self.allow_hidden else 0
            sim = services.object_manager().get(sim_info.id) if sim_info.is_baby else sim_info.get_sim_instance(allow_hidden_flags=allow_hidden_flags)
            if sim is not None:
                yield sim


class GetActualLotObject(_GetObjectsBase):
    def _get_objects_gen(self, resolver=None):
        active_lot = services.active_lot()
        if active_lot is not None:
            yield active_lot


class GetActualLotLevelObjects(_GetObjectsBase):
    def _get_objects_gen(self, resolver=None):
        active_lot = services.active_lot()
        if active_lot is not None:
            yield from active_lot.lot_levels.values()


class ObjectSearchMethodVariant(TunableVariant):

    def __init__(self, *args, **kwargs):
        super().__init__(*args,
                         active_household=GetObjectsByActiveHousehold.TunableFactory(),
                         active_lot=GetObjectsOnActiveLot.TunableFactory(),
                         actual_lot=GetActualLotObject.TunableFactory(),
                         actual_lot_levels=GetActualLotLevelObjects.TunableFactory(),
                         affordance=GetObjectsByAffordance.TunableFactory(),
                         all=GetAllObjects.TunableFactory(),
                         definition=GetObjectsByDefinition.TunableFactory(),
                         inventory=GetObjectsFromInventory.TunableFactory(),
                         participant=GetObjectsByParticipant.TunableFactory(),
                         sim_info=GetObjectsBySimInfo.TunableFactory(),
                         situation_target=GetSituationTargetObject.TunableFactory(),
                         tags=GetObjectsByTags.TunableFactory(),
                         tuning=GetObjectsByTuning.TunableFactory(),
                         default='participant',
                         **kwargs)
