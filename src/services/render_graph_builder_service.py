from __future__ import annotations

from collections import deque
from typing import Any

from src.models.animation_execution import (
    AnimationExecutionPlan,
)
from src.models.audio_track import AudioTrack
from src.models.camera_execution import (
    CameraExecutionPlan,
)
from src.models.effect_execution import (
    EffectExecutionPlan,
)
from src.models.master_edit_plan import (
    MasterEditPlan,
)
from src.models.render_graph import (
    RenderEdge,
    RenderGraph,
    RenderGraphStatus,
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.models.subtitle_execution import (
    SubtitleExecutionPlan,
)
from src.models.transition_execution import (
    TransitionExecutionPlan,
)
from src.models.video_timeline_item import (
    VideoTimelineItem,
)


class RenderGraphBuilderService:
    """
    Build a deterministic provider-independent render graph.

    The graph combines the approved master edit plan with camera,
    transition, effect, animation, subtitle, video, and audio
    execution information.

    No FFmpeg commands are generated or executed here.
    """

    def build(
        self,
        *,
        master_plan: MasterEditPlan,
        transition_plan: TransitionExecutionPlan,
        effect_plan: EffectExecutionPlan,
        subtitle_plan: SubtitleExecutionPlan,
        camera_plan: CameraExecutionPlan,
        animation_plan: AnimationExecutionPlan,
        mark_ready: bool = True,
    ) -> RenderGraph:
        """Build and validate the complete final render graph."""

        if not master_plan.ready_for_render:
            raise ValueError(
                "Render graph requires a render-ready " "master edit plan."
            )

        self._validate_execution_plans(
            transition_plan=transition_plan,
            effect_plan=effect_plan,
            subtitle_plan=subtitle_plan,
            camera_plan=camera_plan,
            animation_plan=animation_plan,
        )

        nodes: list[RenderNode] = []

        video_node_by_scene: dict[int, str] = {}

        for item in master_plan.video_timeline.ordered_items():
            node = self._video_node(item)

            nodes.append(node)

            if item.scene_number in video_node_by_scene:
                raise ValueError(
                    "Render graph does not allow " "duplicate enabled scene numbers."
                )

            video_node_by_scene[item.scene_number] = str(node.id)

        audio_nodes = [
            self._audio_node(track) for track in master_plan.audio_timeline.tracks
        ]

        nodes.extend(audio_nodes)

        camera_nodes = [
            self._camera_node(
                execution=execution,
                video_node_by_scene=(video_node_by_scene),
            )
            for execution in camera_plan.executions
        ]

        transition_nodes = [
            self._transition_node(
                execution=execution,
                video_node_by_scene=(video_node_by_scene),
            )
            for execution in transition_plan.executions
        ]

        effect_nodes = [
            self._effect_node(
                execution=execution,
                video_node_by_scene=(video_node_by_scene),
            )
            for execution in effect_plan.executions
        ]

        animation_nodes = [
            self._animation_node(
                execution=execution,
                video_node_by_scene=(video_node_by_scene),
            )
            for execution in animation_plan.executions
        ]

        subtitle_nodes = [
            self._subtitle_node(
                execution=execution,
                video_node_by_scene=(video_node_by_scene),
            )
            for execution in subtitle_plan.executions
        ]

        editing_nodes = [
            *camera_nodes,
            *transition_nodes,
            *effect_nodes,
            *animation_nodes,
            *subtitle_nodes,
        ]

        nodes.extend(editing_nodes)

        video_nodes = [
            node for node in nodes if (node.node_type == RenderNodeType.VIDEO_CLIP)
        ]

        video_composition_node = self._video_composition_node(
            master_plan=master_plan,
            video_nodes=video_nodes,
            editing_nodes=editing_nodes,
        )

        nodes.append(video_composition_node)

        audio_mix_node = self._audio_mix_node(
            master_plan=master_plan,
            audio_nodes=audio_nodes,
        )

        nodes.append(audio_mix_node)

        output_node = self._output_node(
            master_plan=master_plan,
            video_composition_node=(video_composition_node),
            audio_mix_node=audio_mix_node,
        )

        nodes.append(output_node)

        edges = self._build_edges(nodes)

        graph = RenderGraph(
            status=RenderGraphStatus.DRAFT,
            nodes=nodes,
            edges=edges,
            timeline_duration_seconds=(master_plan.total_duration_seconds),
            scene_count=(master_plan.scene_count),
            node_count=len(nodes),
            edge_count=len(edges),
            ready_node_count=0,
            executed_node_count=0,
            failed_node_count=0,
            is_valid=True,
            is_render_ready=False,
            output_node_id=str(output_node.id),
            warnings=self._collect_warnings(
                master_plan=master_plan,
                transition_plan=transition_plan,
                effect_plan=effect_plan,
                subtitle_plan=subtitle_plan,
                camera_plan=camera_plan,
                animation_plan=animation_plan,
            ),
            metadata={
                "master_plan_id": str(master_plan.id),
                "transition_plan_id": str(transition_plan.id),
                "effect_plan_id": str(effect_plan.id),
                "subtitle_plan_id": str(subtitle_plan.id),
                "camera_plan_id": str(camera_plan.id),
                "animation_plan_id": str(animation_plan.id),
            },
        )

        self.validate_graph(graph)

        if mark_ready:
            self.mark_ready(graph)

        return graph

    def validate_graph(
        self,
        graph: RenderGraph,
    ) -> RenderGraph:
        """
        Validate references, dependency edges, output node,
        and dependency acyclicity.
        """

        errors: list[str] = []

        node_ids = [str(node.id) for node in graph.nodes]

        node_id_set = set(node_ids)

        if len(node_ids) != len(node_id_set):
            errors.append("Render graph contains duplicate node IDs.")

        for node in graph.nodes:
            node_id = str(node.id)

            for dependency_id in node.dependency_ids:
                if dependency_id not in node_id_set:
                    errors.append(
                        "Render node references an unknown "
                        f"dependency: {dependency_id}."
                    )

                if dependency_id == node_id:
                    errors.append("Render node cannot depend " "on itself.")

        expected_edges = {
            (
                dependency_id,
                str(node.id),
            )
            for node in graph.nodes
            for dependency_id in node.dependency_ids
        }

        actual_edges = {
            (
                edge.source_node_id,
                edge.target_node_id,
            )
            for edge in graph.edges
        }

        if expected_edges != actual_edges:
            errors.append("Render graph edges do not match " "node dependencies.")

        if self._has_cycle(graph):
            errors.append("Render graph contains " "a dependency cycle.")

        output_nodes = [
            node for node in graph.nodes if (node.node_type == RenderNodeType.OUTPUT)
        ]

        if len(output_nodes) != 1:
            errors.append("Render graph requires exactly " "one output node.")

        elif graph.output_node_id != str(output_nodes[0].id):
            errors.append(
                "Render graph output node ID " "does not match the output node."
            )

        if errors:
            unique_errors = self._unique_text(errors)

            graph.status = RenderGraphStatus.FAILED

            graph.is_valid = False
            graph.is_render_ready = False

            graph.metadata["validation_errors"] = unique_errors

            raise ValueError(
                "Render graph validation failed. " + " ".join(unique_errors)
            )

        for node in graph.nodes:
            if node.status == RenderNodeStatus.PLANNED:
                node.status = RenderNodeStatus.VALIDATED

        graph.status = RenderGraphStatus.VALIDATED

        graph.metadata["validation_errors"] = []

        graph.refresh_summary()

        graph.is_valid = True

        return graph

    def mark_ready(
        self,
        graph: RenderGraph,
    ) -> RenderGraph:
        """Mark validated graph nodes as renderer-ready."""

        if graph.status == RenderGraphStatus.DRAFT:
            self.validate_graph(graph)

        if not graph.is_valid:
            raise ValueError("Invalid render graph cannot " "be marked ready.")

        for node in graph.nodes:
            if node.status == RenderNodeStatus.VALIDATED:
                node.status = RenderNodeStatus.READY

        graph.refresh_summary()

        graph.is_render_ready = (
            graph.is_valid
            and graph.node_count > 0
            and graph.ready_node_count == graph.node_count
        )

        if not graph.is_render_ready:
            raise ValueError(
                "Render graph could not satisfy " "render-readiness requirements."
            )

        graph.status = RenderGraphStatus.READY

        return graph

    def topological_order(
        self,
        graph: RenderGraph,
    ) -> list[RenderNode]:
        """
        Return nodes in dependency-safe execution order.

        Raises ValueError when a dependency is missing
        or the graph contains a cycle.
        """

        node_by_id = {str(node.id): node for node in graph.nodes}

        indegree: dict[
            str,
            int,
        ] = {node_id: 0 for node_id in node_by_id}

        children: dict[
            str,
            list[str],
        ] = {node_id: [] for node_id in node_by_id}

        for node in graph.nodes:
            target_id = str(node.id)

            for dependency_id in node.dependency_ids:
                if dependency_id not in node_by_id:
                    raise ValueError("Render graph contains " "an unknown dependency.")

                indegree[target_id] += 1

                children[dependency_id].append(target_id)

        queue: deque[str] = deque(
            sorted(
                (node_id for node_id, degree in indegree.items() if degree == 0),
                key=lambda node_id: (
                    node_by_id[node_id].start_time_seconds,
                    node_by_id[node_id].node_type.value,
                    node_id,
                ),
            )
        )

        ordered: list[RenderNode] = []

        while queue:
            node_id = queue.popleft()

            ordered.append(node_by_id[node_id])

            for child_id in sorted(children[node_id]):
                indegree[child_id] -= 1

                if indegree[child_id] == 0:
                    queue.append(child_id)

        if len(ordered) != len(graph.nodes):
            raise ValueError("Render graph contains " "a dependency cycle.")

        return ordered

    def mark_node_executed(
        self,
        graph: RenderGraph,
        *,
        node_id: str,
        renderer: str,
        renderer_metadata: dict[str, Any] | None = None,
    ) -> RenderNode:
        """Mark one ready render node as executed."""

        cleaned_renderer = renderer.strip()

        if not cleaned_renderer:
            raise ValueError("Executed render node requires " "a renderer name.")

        node = self._find_node(
            graph=graph,
            node_id=node_id,
        )

        if node.status not in {
            RenderNodeStatus.READY,
            RenderNodeStatus.EXECUTED,
        }:
            raise ValueError("Only ready render nodes " "can be executed.")

        executed_ids = {
            str(candidate.id)
            for candidate in graph.nodes
            if candidate.status
            in {
                RenderNodeStatus.EXECUTED,
                RenderNodeStatus.SKIPPED,
            }
        }

        missing_dependencies = [
            dependency_id
            for dependency_id in node.dependency_ids
            if dependency_id not in executed_ids
        ]

        if missing_dependencies:
            raise ValueError("Render node dependencies must " "execute first.")

        node.metadata["renderer"] = cleaned_renderer

        node.metadata["renderer_metadata"] = dict(renderer_metadata or {})

        node.status = RenderNodeStatus.EXECUTED

        graph.status = RenderGraphStatus.EXECUTING

        graph.refresh_summary()

        if graph.completed:
            graph.status = RenderGraphStatus.COMPLETED

        return node

    def mark_node_failed(
        self,
        graph: RenderGraph,
        *,
        node_id: str,
        error_message: str,
        failure_metadata: dict[str, Any] | None = None,
    ) -> RenderNode:
        """Mark one render node as failed."""

        cleaned_message = error_message.strip()

        if not cleaned_message:
            raise ValueError("Render-node failure message " "cannot be empty.")

        node = self._find_node(
            graph=graph,
            node_id=node_id,
        )

        node.status = RenderNodeStatus.FAILED

        node.metadata["failure_message"] = cleaned_message

        node.metadata["failure_details"] = dict(failure_metadata or {})

        warning = "Render node failed: " f"{cleaned_message}"

        if warning not in node.warnings:
            node.warnings.append(warning)

        graph.warnings = self._unique_text(
            [
                *graph.warnings,
                warning,
            ]
        )

        graph.status = RenderGraphStatus.FAILED

        graph.refresh_summary()

        graph.is_valid = False
        graph.is_render_ready = False

        return node

    def summary(
        self,
        graph: RenderGraph,
    ) -> dict[str, Any]:
        """Return serializable render-graph summary."""

        graph.refresh_summary()

        node_type_counts: dict[
            str,
            int,
        ] = {
            node_type.value: sum(
                1 for node in graph.nodes if (node.node_type == node_type)
            )
            for node_type in RenderNodeType
        }

        return {
            "graph_id": str(graph.id),
            "status": (graph.status.value),
            "timeline_duration_seconds": (graph.timeline_duration_seconds),
            "scene_count": (graph.scene_count),
            "node_count": (graph.node_count),
            "edge_count": (graph.edge_count),
            "ready_node_count": (graph.ready_node_count),
            "executed_node_count": (graph.executed_node_count),
            "failed_node_count": (graph.failed_node_count),
            "is_valid": (graph.is_valid),
            "is_render_ready": (graph.is_render_ready),
            "output_node_id": (graph.output_node_id),
            "node_type_counts": (node_type_counts),
            "warnings": list(graph.warnings),
            "metadata": dict(graph.metadata),
        }

    @staticmethod
    def _video_node(
        item: VideoTimelineItem,
    ) -> RenderNode:
        """Build one video source node."""

        return RenderNode(
            node_type=(RenderNodeType.VIDEO_CLIP),
            scene_number=(item.scene_number),
            track_index=(item.track_index),
            layer_index=(item.layer_index),
            start_time_seconds=(item.start_time_seconds),
            end_time_seconds=(item.end_time_seconds),
            duration_seconds=(item.duration_seconds),
            source_reference_id=str(item.id),
            payload={
                "local_file": (item.clip.local_file),
                "source_url": (item.clip.source_url),
                "clip_id": str(item.clip.id),
            },
        )

    @staticmethod
    def _audio_node(
        track: AudioTrack,
    ) -> RenderNode:
        """Build one audio source node."""

        start_time = track.start_time_seconds

        end_time = start_time + track.duration_seconds

        raw_scene_number = track.metadata.get("scene_number")

        scene_number: int | None

        if (
            isinstance(
                raw_scene_number,
                int,
            )
            and raw_scene_number >= 1
        ):
            scene_number = raw_scene_number
        else:
            scene_number = None

        return RenderNode(
            node_type=(RenderNodeType.AUDIO_TRACK),
            scene_number=scene_number,
            start_time_seconds=(start_time),
            end_time_seconds=(end_time),
            duration_seconds=(track.duration_seconds),
            source_reference_id=str(track.id),
            payload={
                "track_type": (track.track_type.value),
                "source_file": (track.source_file),
                "volume": (track.volume),
                "fade_in_seconds": (track.fade_in_seconds),
                "fade_out_seconds": (track.fade_out_seconds),
                "loop_enabled": (track.loop_enabled),
                "duck_under_voice": (track.duck_under_voice),
                "provider": (track.provider),
            },
        )

    @staticmethod
    def _camera_node(
        *,
        execution: Any,
        video_node_by_scene: dict[
            int,
            str,
        ],
    ) -> RenderNode:
        """Build one camera execution node."""

        dependency = RenderGraphBuilderService._scene_dependency(
            scene_number=(execution.scene_number),
            video_node_by_scene=(video_node_by_scene),
        )

        return RenderNode(
            node_type=(RenderNodeType.CAMERA),
            scene_number=(execution.scene_number),
            track_index=(execution.track_index),
            layer_index=(execution.layer_index),
            start_time_seconds=(execution.start_time_seconds),
            end_time_seconds=(execution.end_time_seconds),
            duration_seconds=(execution.duration_seconds),
            dependency_ids=[dependency],
            source_reference_id=str(execution.id),
            payload=(execution.model_dump(mode="json")),
        )

    @staticmethod
    def _transition_node(
        *,
        execution: Any,
        video_node_by_scene: dict[
            int,
            str,
        ],
    ) -> RenderNode:
        """Build one transition execution node."""

        dependencies: list[str] = []

        if execution.source_scene_number is not None:
            dependencies.append(
                RenderGraphBuilderService._scene_dependency(
                    scene_number=(execution.source_scene_number),
                    video_node_by_scene=(video_node_by_scene),
                )
            )

        if execution.target_scene_number is not None:
            target_dependency = RenderGraphBuilderService._scene_dependency(
                scene_number=(execution.target_scene_number),
                video_node_by_scene=(video_node_by_scene),
            )

            if target_dependency not in dependencies:
                dependencies.append(target_dependency)

        track_index: int | None = execution.source_track_index

        if track_index is None:
            track_index = execution.target_track_index

        scene_number = execution.source_scene_number

        if scene_number is None:
            scene_number = execution.target_scene_number

        return RenderNode(
            node_type=(RenderNodeType.TRANSITION),
            scene_number=scene_number,
            track_index=track_index,
            start_time_seconds=(execution.start_time_seconds),
            end_time_seconds=(execution.end_time_seconds),
            duration_seconds=(execution.duration_seconds),
            dependency_ids=(dependencies),
            source_reference_id=str(execution.id),
            payload=(execution.model_dump(mode="json")),
        )

    @staticmethod
    def _effect_node(
        *,
        execution: Any,
        video_node_by_scene: dict[
            int,
            str,
        ],
    ) -> RenderNode:
        """Build one visual-effect execution node."""

        return RenderGraphBuilderService._scene_execution_node(
            node_type=(RenderNodeType.VISUAL_EFFECT),
            execution=execution,
            video_node_by_scene=(video_node_by_scene),
        )

    @staticmethod
    def _animation_node(
        *,
        execution: Any,
        video_node_by_scene: dict[
            int,
            str,
        ],
    ) -> RenderNode:
        """Build one animation execution node."""

        return RenderGraphBuilderService._scene_execution_node(
            node_type=(RenderNodeType.ANIMATION),
            execution=execution,
            video_node_by_scene=(video_node_by_scene),
        )

    @staticmethod
    def _subtitle_node(
        *,
        execution: Any,
        video_node_by_scene: dict[
            int,
            str,
        ],
    ) -> RenderNode:
        """Build one subtitle execution node."""

        return RenderGraphBuilderService._scene_execution_node(
            node_type=(RenderNodeType.SUBTITLE),
            execution=execution,
            video_node_by_scene=(video_node_by_scene),
        )

    @staticmethod
    def _scene_execution_node(
        *,
        node_type: RenderNodeType,
        execution: Any,
        video_node_by_scene: dict[
            int,
            str,
        ],
    ) -> RenderNode:
        """Build a generic scene-dependent execution node."""

        dependency = RenderGraphBuilderService._scene_dependency(
            scene_number=(execution.scene_number),
            video_node_by_scene=(video_node_by_scene),
        )

        raw_track_index = getattr(
            execution,
            "track_index",
            None,
        )

        track_index = (
            raw_track_index
            if isinstance(
                raw_track_index,
                int,
            )
            else None
        )

        raw_layer_index = getattr(
            execution,
            "layer_index",
            None,
        )

        layer_index = (
            raw_layer_index
            if isinstance(
                raw_layer_index,
                int,
            )
            else None
        )

        return RenderNode(
            node_type=node_type,
            scene_number=(execution.scene_number),
            track_index=track_index,
            layer_index=layer_index,
            start_time_seconds=(execution.start_time_seconds),
            end_time_seconds=(execution.end_time_seconds),
            duration_seconds=(execution.duration_seconds),
            dependency_ids=[dependency],
            source_reference_id=str(execution.id),
            payload=(execution.model_dump(mode="json")),
        )

    @staticmethod
    def _video_composition_node(
        *,
        master_plan: MasterEditPlan,
        video_nodes: list[RenderNode],
        editing_nodes: list[RenderNode],
    ) -> RenderNode:
        """Build final video-composition node."""

        dependencies = [
            str(node.id)
            for node in [
                *video_nodes,
                *editing_nodes,
            ]
        ]

        duration = master_plan.video_duration_seconds

        return RenderNode(
            node_type=(RenderNodeType.VIDEO_COMPOSITION),
            start_time_seconds=0.0,
            end_time_seconds=duration,
            duration_seconds=duration,
            dependency_ids=(dependencies),
            payload={
                "output_resolution": (master_plan.video_timeline.output_resolution),
                "frame_rate": (master_plan.video_timeline.frame_rate),
            },
        )

    @staticmethod
    def _audio_mix_node(
        *,
        master_plan: MasterEditPlan,
        audio_nodes: list[RenderNode],
    ) -> RenderNode:
        """Build final audio-mix node."""

        duration = master_plan.audio_duration_seconds

        return RenderNode(
            node_type=(RenderNodeType.AUDIO_MIX),
            start_time_seconds=0.0,
            end_time_seconds=duration,
            duration_seconds=duration,
            dependency_ids=[str(node.id) for node in audio_nodes],
            payload={
                "sample_rate": (master_plan.audio_timeline.sample_rate),
                "channels": (master_plan.audio_timeline.channels),
            },
        )

    @staticmethod
    def _output_node(
        *,
        master_plan: MasterEditPlan,
        video_composition_node: RenderNode,
        audio_mix_node: RenderNode,
    ) -> RenderNode:
        """Build final output node."""

        duration = master_plan.total_duration_seconds

        return RenderNode(
            node_type=(RenderNodeType.OUTPUT),
            start_time_seconds=0.0,
            end_time_seconds=duration,
            duration_seconds=duration,
            dependency_ids=[
                str(video_composition_node.id),
                str(audio_mix_node.id),
            ],
            payload={
                "container": "mp4",
                "video_codec": None,
                "audio_codec": None,
            },
        )

    @staticmethod
    def _build_edges(
        nodes: list[RenderNode],
    ) -> list[RenderEdge]:
        """Build dependency edges from node dependencies."""

        edges: list[RenderEdge] = []

        for node in nodes:
            for dependency_id in node.dependency_ids:
                edges.append(
                    RenderEdge(
                        source_node_id=(dependency_id),
                        target_node_id=str(node.id),
                    )
                )

        return edges

    @staticmethod
    def _scene_dependency(
        *,
        scene_number: int,
        video_node_by_scene: dict[
            int,
            str,
        ],
    ) -> str:
        """Resolve video-node dependency for one scene."""

        dependency = video_node_by_scene.get(scene_number)

        if dependency is None:
            raise ValueError(
                "Execution plan references "
                "a scene missing from video timeline: "
                f"{scene_number}."
            )

        return dependency

    @staticmethod
    def _validate_execution_plans(
        *,
        transition_plan: TransitionExecutionPlan,
        effect_plan: EffectExecutionPlan,
        subtitle_plan: SubtitleExecutionPlan,
        camera_plan: CameraExecutionPlan,
        animation_plan: AnimationExecutionPlan,
    ) -> None:
        """
        Validate every execution-plan contract explicitly.

        Explicit checks preserve concrete plan types for mypy.
        """

        if not transition_plan.is_valid:
            raise ValueError("Transition execution plan is invalid.")

        if not transition_plan.is_render_ready:
            raise ValueError("Transition execution plan is not " "render-ready.")

        if not effect_plan.is_valid:
            raise ValueError("Effect execution plan is invalid.")

        if not effect_plan.is_render_ready:
            raise ValueError("Effect execution plan is not " "render-ready.")

        if not subtitle_plan.is_valid:
            raise ValueError("Subtitle execution plan is invalid.")

        if not subtitle_plan.is_render_ready:
            raise ValueError("Subtitle execution plan is not " "render-ready.")

        if not camera_plan.is_valid:
            raise ValueError("Camera execution plan is invalid.")

        if not camera_plan.is_render_ready:
            raise ValueError("Camera execution plan is not " "render-ready.")

        if not animation_plan.is_valid:
            raise ValueError("Animation execution plan is invalid.")

        if not animation_plan.is_render_ready:
            raise ValueError("Animation execution plan is not " "render-ready.")

    @staticmethod
    def _collect_warnings(
        *,
        master_plan: MasterEditPlan,
        transition_plan: TransitionExecutionPlan,
        effect_plan: EffectExecutionPlan,
        subtitle_plan: SubtitleExecutionPlan,
        camera_plan: CameraExecutionPlan,
        animation_plan: AnimationExecutionPlan,
    ) -> list[str]:
        """Collect stable warnings from all render inputs."""

        return RenderGraphBuilderService._unique_text(
            [
                *master_plan.warnings,
                *transition_plan.warnings,
                *effect_plan.warnings,
                *subtitle_plan.warnings,
                *camera_plan.warnings,
                *animation_plan.warnings,
            ]
        )

    @staticmethod
    def _has_cycle(
        graph: RenderGraph,
    ) -> bool:
        """Return whether graph dependencies contain a cycle."""

        service = RenderGraphBuilderService()

        try:
            service.topological_order(graph)
        except ValueError:
            return True

        return False

    @staticmethod
    def _find_node(
        *,
        graph: RenderGraph,
        node_id: str,
    ) -> RenderNode:
        """Return one render node by ID."""

        cleaned = node_id.strip()

        if not cleaned:
            raise ValueError("Render node ID cannot be empty.")

        matches = [node for node in graph.nodes if str(node.id) == cleaned]

        if not matches:
            raise KeyError("Render node was not found: " f"{cleaned}")

        if len(matches) > 1:
            raise ValueError("Multiple render nodes share " "the same ID.")

        return matches[0]

    @staticmethod
    def _unique_text(
        values: list[str],
    ) -> list[str]:
        """Return normalized unique text values."""

        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned
