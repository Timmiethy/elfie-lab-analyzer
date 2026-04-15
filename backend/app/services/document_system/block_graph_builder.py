from __future__ import annotations

from .contracts import BlockEdgeV1, BlockGraphV1, BlockNodeV1, PageParseArtifactV4


class BlockGraphBuilder:
    """Build BlockGraphV1 from PageParseArtifactV4."""

    def build(self, artifact: PageParseArtifactV4) -> BlockGraphV1:
        nodes: list[BlockNodeV1] = []
        for reading_order, block in enumerate(artifact.blocks):
            nodes.append(
                BlockNodeV1(
                    node_id=f"{artifact.page_id}:node-{reading_order:03d}",
                    block_id=block.block_id,
                    block_role=block.block_role,
                    text=block.raw_text,
                    page_number=artifact.page_number,
                    reading_order=reading_order,
                    lines=list(block.lines),
                    bbox=block.bbox,
                    language_tags=list(block.language_tags),
                    source_spans=list(block.source_spans),
                    metadata={
                        **block.metadata,
                        "line_count": len(block.lines),
                    },
                )
            )

        edges = _link_edges(nodes)
        return BlockGraphV1(
            page_id=artifact.page_id,
            page_number=artifact.page_number,
            nodes=nodes,
            edges=edges,
            metadata={
                "backend_id": artifact.backend_id,
                "backend_version": artifact.backend_version,
                "lane_type": artifact.lane_type,
                "page_kind": artifact.page_kind.value,
            },
        )


def _link_edges(nodes: list[BlockNodeV1]) -> list[BlockEdgeV1]:
    edges: list[BlockEdgeV1] = []
    for index in range(len(nodes) - 1):
        current = nodes[index]
        next_node = nodes[index + 1]
        edges.append(
            BlockEdgeV1(
                source_node_id=current.node_id,
                target_node_id=next_node.node_id,
                relation="next_in_reading_order",
            )
        )

        if current.bbox is not None and next_node.bbox is not None:
            vertical_gap = max(0.0, next_node.bbox.y0 - current.bbox.y1)
            if vertical_gap <= 18.0:
                edges.append(
                    BlockEdgeV1(
                        source_node_id=current.node_id,
                        target_node_id=next_node.node_id,
                        relation="adjacent_vertical_block",
                    )
                )
    return edges
